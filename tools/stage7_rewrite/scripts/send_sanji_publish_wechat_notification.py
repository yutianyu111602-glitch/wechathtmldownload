#!/usr/bin/env python3
"""Send a best-effort Hermes/Weixin notification for Sanji daily publish results.

The script is intentionally secret-safe. By default it calls Hermes' native
Weixin send path and falls back to webhook URLs from environment variables.
OpenClaw/iMessage remains an explicit fallback only. The report never writes raw
endpoint URLs or notification target IDs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


ENDPOINT_ENV_KEYS = (
    "HUAIDJ_WECHAT_NOTIFY_WEBHOOK",
    "OPENCLAW_WECHAT_BOT_WEBHOOK",
    "CLAWBOT_WEBHOOK_URL",
)

HERMES_ENV_KEYS = (
    "HUAIDJ_WECHAT_NOTIFY_DRIVER",
    "HUAIDJ_HERMES_HOME",
    "HUAIDJ_HERMES_AGENT_ROOT",
    "HUAIDJ_HERMES_PYTHON",
    "HUAIDJ_HERMES_GATEWAY_DELIVER",
    "HUAIDJ_HERMES_NOTIFY_TARGET",
    "HUAIDJ_HERMES_WEIXIN_TARGET",
    "HUAIDJ_ALLOW_IMESSAGE_FALLBACK",
)

OPENCLAW_DEFAULT_CHANNEL = "imessage"
OPENCLAW_DEFAULT_ACCOUNT = "macbook-bot"

OPENCLAW_ENV_KEYS = (
    "HUAIDJ_WECHAT_NOTIFY_DRIVER",
    "HUAIDJ_OPENCLAW_NOTIFY_COMMAND",
    "HUAIDJ_OPENCLAW_NOTIFY_CHANNEL",
    "HUAIDJ_OPENCLAW_NOTIFY_TARGET",
    "HUAIDJ_OPENCLAW_NOTIFY_ACCOUNT",
)

USAGE_SUMMARY_FILENAMES = (
    "llm_usage_summary.json",
    "poster_vl_usage_summary.json",
    "qwen_vl_usage_summary.json",
)

WINDOWS_TASK_NAMES = (
    "HUAIDJ Sanji Daily Publish Noon",
    "HUAIDJ Sanji Daily Publish Evening",
    "HUAIDJ Sanji RSS Fast Watch",
    "HUAIDJ Sanji Desktop Export Noon",
    "HUAIDJ Sanji Desktop Export Evening",
)

HERMES_JOB_NAMES = (
    "HUAIDJ Sanji Wed 21:10",
    "HUAIDJ Sanji Fri 20:10",
    "HUAIDJ Sanji Wed+Fri 14:30",
    "HUAIDJ Sanji Publish Noon",
    "HUAIDJ Sanji Publish Evening",
    "HUAIDJ Sanji RSS Fast Watch",
    "HUAIDJ Coverage Audit Wed 22:40",
    "HUAIDJ Coverage Audit Fri 21:40",
    "HUAIDJ Coverage Audit (post-pipeline)",
    "HUAIDJ 全栈健康检查",
)

_WINDOWS_SCHEDULER_STATUS_CACHE: list[dict[str, Any]] | None = None
_HERMES_SCHEDULER_STATUS_CACHE: list[dict[str, Any]] | None = None


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def short_hash(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def redact_for_report(text: str, target: str = "") -> str:
    if not text:
        return ""
    redacted = text
    if target:
        redacted = redacted.replace(target, "<redacted-target>")
        if ":" in target:
            redacted = redacted.replace(target.split(":", 1)[1], "<redacted-target>")
    redacted = re.sub(r"\bwxid_[A-Za-z0-9_-]+\b", "<redacted-weixin-id>", redacted)
    redacted = re.sub(r"\b[A-Za-z0-9_-]+@im\.wechat\b", "<redacted-weixin-id>", redacted)
    redacted = re.sub(r"\+?\d[\d -]{5,}\d", "<redacted-phone>", redacted)
    redacted = re.sub(r"[A-Za-z0-9._%+-]{3,}@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "<redacted-email>", redacted)
    return redacted


def first_existing_env(keys: tuple[str, ...] = ENDPOINT_ENV_KEYS) -> tuple[str, str]:
    for key in keys:
        value = os.environ.get(key, "").strip()
        if value:
            return key, value
    return "", ""


def discover_publish_summary(status: dict[str, Any]) -> Path | None:
    explicit_path = Path(str(status.get("publish_summary_path") or ""))
    if explicit_path.is_file():
        return explicit_path

    log_path = Path(str(status.get("log_path") or ""))
    if log_path.is_file():
        text = log_path.read_text(encoding="utf-8", errors="replace")
        matches = re.findall(
            r"OpenClaw weekly daily runbook complete:\s*(.+?openclaw_weekly_daily_publish_summary\.json)",
            text,
        )
        if matches:
            candidate = Path(matches[-1].strip())
            if candidate.exists():
                return candidate

    if not status.get("ok"):
        return None

    repo = Path(str(status.get("repo") or r"C:\code\githubstar\wechathtmldownload"))
    reports = repo / "tools" / "stage7_rewrite" / "reports"
    if not reports.exists():
        return None
    candidates = sorted(
        reports.glob("openclaw_weekly_daily_*/openclaw_weekly_daily_publish_summary.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def maybe_load(path: Path | None) -> dict[str, Any]:
    if path and path.exists():
        try:
            return load_json(path)
        except Exception:
            return {}
    return {}


def report_dir_from_summary(summary_path: Path | None) -> Path | None:
    return summary_path.parent if summary_path else None


def cloudrun_report_path(summary: dict[str, Any], summary_path: Path | None) -> Path | None:
    run_id = str(summary.get("run_id") or "")
    if not run_id:
        return None
    base = summary_path.parents[1] if summary_path and len(summary_path.parents) > 1 else None
    if base is None:
        return None
    candidate = base / f"cloudrun_direct_deploy_{run_id}" / "cloudrun_direct_api_deploy_report.json"
    return candidate if candidate.exists() else None


def count_value(obj: dict[str, Any], *keys: str) -> Any:
    cur: Any = obj
    for key in keys:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None
    return cur


def as_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        items = payload.get("items")
    else:
        items = payload
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def any_field(item: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(has_value(item.get(key)) for key in keys)


def rate(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "0/0"
    return f"{numerator}/{denominator} ({numerator / denominator:.0%})"


def collect_windows_scheduler_status() -> list[dict[str, Any]]:
    global _WINDOWS_SCHEDULER_STATUS_CACHE
    if _WINDOWS_SCHEDULER_STATUS_CACHE is not None:
        return _WINDOWS_SCHEDULER_STATUS_CACHE
    if os.name != "nt":
        _WINDOWS_SCHEDULER_STATUS_CACHE = []
        return []
    ps = shutil.which("powershell.exe") or shutil.which("powershell")
    if not ps:
        _WINDOWS_SCHEDULER_STATUS_CACHE = []
        return []
    names_json = json.dumps(list(WINDOWS_TASK_NAMES), ensure_ascii=False)
    script = rf"""
$names = ConvertFrom-Json @'
{names_json}
'@
$items = @()
foreach ($name in $names) {{
  $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
  $info = Get-ScheduledTaskInfo -TaskName $name -ErrorAction SilentlyContinue
  if ($task -and $info) {{
    $items += [pscustomobject]@{{
      task_name = $name
      state = [string]$task.State
      last_run_time = if ($info.LastRunTime) {{ $info.LastRunTime.ToString("yyyy-MM-dd HH:mm") }} else {{ "" }}
      last_task_result = [int]$info.LastTaskResult
      next_run_time = if ($info.NextRunTime) {{ $info.NextRunTime.ToString("yyyy-MM-dd HH:mm") }} else {{ "" }}
    }}
  }}
}}
$items | ConvertTo-Json -Depth 4
"""
    try:
        proc = subprocess.run(
            [ps, "-NoProfile", "-Command", script],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=12,
            check=False,
        )
    except Exception:
        _WINDOWS_SCHEDULER_STATUS_CACHE = []
        return []
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        _WINDOWS_SCHEDULER_STATUS_CACHE = []
        return []
    try:
        payload = json.loads(proc.stdout)
    except Exception:
        _WINDOWS_SCHEDULER_STATUS_CACHE = []
        return []
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        payload = []
    _WINDOWS_SCHEDULER_STATUS_CACHE = [row for row in payload if isinstance(row, dict)]
    return _WINDOWS_SCHEDULER_STATUS_CACHE


def render_scheduler_status(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return ""
    labels = {
        "HUAIDJ Sanji Daily Publish Noon": "发布noon",
        "HUAIDJ Sanji Daily Publish Evening": "发布evening",
        "HUAIDJ Sanji RSS Fast Watch": "RSS快触发",
        "HUAIDJ Sanji Desktop Export Noon": "导出noon",
        "HUAIDJ Sanji Desktop Export Evening": "导出evening",
    }
    lines: list[str] = ["Windows任务"]
    for task in tasks:
        name = str(task.get("task_name") or "")
        label = labels.get(name, name.replace("HUAIDJ Sanji ", ""))
        state = str(task.get("state") or "")
        result = task.get("last_task_result")
        if state.lower() == "running":
            result_text = "RUNNING"
        else:
            result_text = "OK" if result == 0 else f"FAIL({result})"
        last_run = str(task.get("last_run_time") or "")
        next_run = str(task.get("next_run_time") or "")
        suffix = ""
        if last_run or next_run:
            suffix = f" | last {last_run or '-'} | next {next_run or '-'}"
        lines.append(f"- {label}: {state} / {result_text}{suffix}")
    return "\n".join(lines)


def collect_hermes_scheduler_status() -> list[dict[str, Any]]:
    global _HERMES_SCHEDULER_STATUS_CACHE
    if _HERMES_SCHEDULER_STATUS_CACHE is not None:
        return _HERMES_SCHEDULER_STATUS_CACHE
    try:
        jobs_path = default_hermes_home() / "cron" / "jobs.json"
    except Exception:
        _HERMES_SCHEDULER_STATUS_CACHE = []
        return []
    payload = maybe_load(jobs_path)
    jobs = payload.get("jobs") if isinstance(payload.get("jobs"), list) else []
    selected: list[dict[str, Any]] = []
    wanted = set(HERMES_JOB_NAMES)
    for job in jobs:
        if not isinstance(job, dict):
            continue
        name = str(job.get("name") or "")
        if name not in wanted:
            continue
        selected.append(
            {
                "job_name": name,
                "state": str(job.get("state") or ""),
                "enabled": bool(job.get("enabled", True)),
                "last_run_at": str(job.get("last_run_at") or ""),
                "next_run_at": str(job.get("next_run_at") or ""),
                "last_status": str(job.get("last_status") or ""),
            }
        )
    _HERMES_SCHEDULER_STATUS_CACHE = selected
    return selected


def _short_dt(value: str) -> str:
    if not value:
        return ""
    text = value.replace("T", " ")
    return text[:16]


def render_hermes_scheduler_status(jobs: list[dict[str, Any]]) -> str:
    if not jobs:
        return ""
    labels = {
        "HUAIDJ Sanji Publish Noon": "发布noon",
        "HUAIDJ Sanji Publish Evening": "发布evening",
        "HUAIDJ Sanji Wed 21:10": "周三21:10发布",
        "HUAIDJ Sanji Fri 20:10": "周五20:10发布",
        "HUAIDJ Sanji Wed+Fri 14:30": "周三/周五发布",
        "HUAIDJ Sanji RSS Fast Watch": "RSS快触发",
        "HUAIDJ Coverage Audit Wed 22:40": "周三覆盖审计",
        "HUAIDJ Coverage Audit Fri 21:40": "周五覆盖审计",
        "HUAIDJ Coverage Audit (post-pipeline)": "覆盖审计",
        "HUAIDJ 全栈健康检查": "全栈健康检查",
    }
    lines: list[str] = ["Hermes任务"]
    for job in jobs:
        name = str(job.get("job_name") or "")
        label = labels.get(name, name.replace("HUAIDJ Sanji ", ""))
        enabled = bool(job.get("enabled", True))
        state = str(job.get("state") or "")
        status = str(job.get("last_status") or "-")
        if not enabled:
            state = "paused"
        last_run = _short_dt(str(job.get("last_run_at") or ""))
        next_run = _short_dt(str(job.get("next_run_at") or ""))
        suffix = ""
        if last_run or next_run:
            suffix = f" | last {last_run or '-'} | next {next_run or '-'}"
        lines.append(f"- {label}: {state} / {status}{suffix}")
    return "\n".join(lines)


def current_json_path(summary: dict[str, Any]) -> Path | None:
    api_dir = str(summary.get("api_dir") or "").strip()
    if not api_dir:
        return None
    candidate = Path(api_dir) / "current.json"
    return candidate if candidate.exists() else None


def load_current_items(summary: dict[str, Any]) -> list[dict[str, Any]]:
    path = current_json_path(summary)
    if not path:
        return []
    try:
        return as_items(load_json(path))
    except Exception:
        return []


def as_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        if not match:
            return None
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None


def first_value(obj: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
    return None


def coerce_int(value: Any) -> int | None:
    number = as_number(value)
    return int(number) if number is not None else None


def collect_usage_summary_search_paths(context: dict[str, Any]) -> list[Path]:
    summary = context.get("summary") or {}
    bases: list[Path] = []
    for raw in (
        context.get("run_dir"),
        Path(str(context.get("summary_path"))).parent if context.get("summary_path") else "",
        summary.get("api_dir"),
        Path(str(summary.get("api_dir"))) / "llm" if summary.get("api_dir") else "",
    ):
        if not raw:
            continue
        try:
            path = Path(str(raw))
        except TypeError:
            continue
        if path.exists() and path.is_dir():
            bases.append(path)

    seen: set[str] = set()
    paths: list[Path] = []
    for base in bases:
        for name in USAGE_SUMMARY_FILENAMES:
            candidate = base / name
            key = str(candidate).lower()
            if key in seen:
                continue
            seen.add(key)
            paths.append(candidate)
    return paths


def normalize_usage_summary(payload: dict[str, Any], source_path: Path) -> dict[str, Any]:
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    billing = payload.get("billing") if isinstance(payload.get("billing"), dict) else {}
    model_info = payload.get("model") if isinstance(payload.get("model"), dict) else {}
    merged: dict[str, Any] = {}
    for part in (payload, usage, billing, model_info):
        if isinstance(part, dict):
            merged.update(part)

    exact_cost = first_value(
        merged,
        (
            "cost_cny",
            "actual_cost_cny",
            "billing_cost_cny",
            "total_cost_cny",
            "dashscope_cost_cny",
            "qwen_cost_cny",
        ),
    )
    estimated_cost = first_value(
        merged,
        (
            "estimated_cost_cny",
            "estimated_llm_cost_cny",
            "cost_estimate_cny",
        ),
    )
    prompt_tokens = coerce_int(first_value(merged, ("prompt_tokens", "input_tokens", "input_token_count")))
    completion_tokens = coerce_int(first_value(merged, ("completion_tokens", "output_tokens", "output_token_count")))
    total_tokens = coerce_int(first_value(merged, ("total_tokens", "token_count")))
    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        total_tokens = prompt_tokens + completion_tokens

    exact_available = bool(payload.get("exact_available")) or exact_cost not in (None, "")
    result = {
        "exact_available": exact_available,
        "source_path": str(source_path),
        "provider": first_value(merged, ("provider", "provider_name", "vl_provider")),
        "model": first_value(merged, ("model", "model_name", "poster_vl_model")),
        "call_count": coerce_int(first_value(merged, ("call_count", "request_count", "vl_call_count", "poster_vl_call_count"))),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "currency": first_value(merged, ("currency",)) or "CNY",
        "note": first_value(merged, ("note", "usage_note")) or "from_llm_usage_summary",
    }
    if exact_cost not in (None, ""):
        result["cost_cny"] = exact_cost
    if estimated_cost not in (None, ""):
        result["estimated_cost_cny"] = estimated_cost
    return result


def load_llm_usage_summary(context: dict[str, Any]) -> dict[str, Any]:
    for path in collect_usage_summary_search_paths(context):
        if not path.exists():
            continue
        try:
            payload = load_json(path)
        except Exception as exc:
            return {
                "exact_available": False,
                "source_path": str(path),
                "note": f"usage_summary_read_failed:{type(exc).__name__}",
            }
        if isinstance(payload, dict):
            return normalize_usage_summary(payload, path)
    return {}


def iter_usage_blocks(value: Any) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            usage = current.get("usage")
            if isinstance(usage, dict) and any(
                key in usage for key in ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens")
            ):
                blocks.append(usage)
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return blocks


def collect_enrichment_usage_snapshot(summary: dict[str, Any]) -> dict[str, Any]:
    api_dir = str(summary.get("api_dir") or "").strip()
    if not api_dir:
        return {}
    enrichments = Path(api_dir) / "llm" / "enrichments"
    if not enrichments.exists() or not enrichments.is_dir():
        return {}

    files = sorted(enrichments.glob("*.json"))
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    usage_file_count = 0
    nonzero_usage_file_count = 0
    for path in files:
        try:
            payload = load_json(path)
        except Exception:
            continue
        blocks = iter_usage_blocks(payload)
        if not blocks:
            continue
        usage_file_count += 1
        file_total = 0
        for block in blocks:
            prompt = coerce_int(first_value(block, ("prompt_tokens", "input_tokens"))) or 0
            completion = coerce_int(first_value(block, ("completion_tokens", "output_tokens"))) or 0
            total = coerce_int(first_value(block, ("total_tokens",))) or prompt + completion
            prompt_tokens += prompt
            completion_tokens += completion
            total_tokens += total
            file_total += total
        if file_total:
            nonzero_usage_file_count += 1

    if not files:
        return {}
    return {
        "source": str(enrichments),
        "file_count": len(files),
        "usage_file_count": usage_file_count,
        "nonzero_usage_file_count": nonzero_usage_file_count,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "note": (
            "api_enrichment_usage_nonzero"
            if nonzero_usage_file_count
            else "api_enrichment_usage_zero_not_billing_usage"
        ),
    }


def estimate_llm_cost(context: dict[str, Any], item_count: int) -> dict[str, Any]:
    """Return an explicit estimate only when exact usage is absent.

    Upstream Qwen/DashScope usage is not always persisted by the VL worker yet.
    We avoid pretending to have exact billing data; the estimate is deliberately
    marked as such and can be replaced once token usage lands in reports.
    """

    summary = context.get("summary") or {}
    usage_summary = load_llm_usage_summary(context)
    if usage_summary:
        if usage_summary.get("cost_cny") not in (None, ""):
            usage_summary["exact_available"] = True
            return usage_summary
        if usage_summary.get("estimated_cost_cny") not in (None, ""):
            calls = int(usage_summary.get("call_count") or item_count or 0)
            usage_summary.update(
                {
                    "exact_available": False,
                    "call_count_estimate": calls,
                    "estimated_range_cny": str(usage_summary.get("estimated_cost_cny")),
                    "note": usage_summary.get("note") or "from_llm_usage_summary_estimate",
                }
            )
            return usage_summary

    exact = (
        summary.get("llm_cost_cny")
        or summary.get("poster_vl_cost_cny")
        or summary.get("dashscope_cost_cny")
    )
    if exact not in (None, ""):
        return {
            "exact_available": True,
            "cost_cny": exact,
            "note": "from_publish_summary",
        }
    estimated = summary.get("estimated_llm_cost_cny")
    if estimated not in (None, ""):
        return {
            "exact_available": False,
            "estimated_range_cny": str(estimated),
            "call_count_estimate": int(summary.get("poster_vl_call_count") or summary.get("vl_call_count") or item_count or 0),
            "note": "estimated_from_publish_summary",
        }
    calls = int(summary.get("poster_vl_call_count") or summary.get("vl_call_count") or item_count or 0)
    # Conservative notification-only estimate used when provider usage is not
    # written: a high-quality VL article call usually lands in a few fen range.
    low = round(calls * 0.02, 2)
    high = round(calls * 0.08, 2)
    return {
        "exact_available": False,
        "call_count_estimate": calls,
        "estimated_range_cny": f"{low}-{high}",
        "note": "exact_usage_not_recorded",
        "usage_snapshot": collect_enrichment_usage_snapshot(summary),
    }


def collect_release_metrics(context: dict[str, Any]) -> dict[str, Any]:
    summary = context.get("summary") or {}
    gap = context.get("gap") or {}
    quality = context.get("quality") or {}
    field_audit = context.get("field_audit") or {}
    items = load_current_items(summary)
    item_count = len(items) or int(summary.get("item_count") or quality.get("item_count") or 0)

    lineup_keys = ("lineup", "lineup_artists", "lineupItems", "poster_vl_lineup", "posterVlLineup")
    price_keys = (
        "price",
        "prices",
        "price_text",
        "priceText",
        "ticket",
        "ticket_info",
        "ticketInfo",
        "ticketing",
        "admission",
        "fee",
    )
    time_keys = (
        "event_time_text",
        "eventTimeText",
        "event_time",
        "eventTime",
        "event_time_start",
        "time_start",
        "timeStart",
        "time",
        "timeText",
    )
    poster_keys = (
        "poster_file_id",
        "posterFileId",
        "cloudFileId",
        "cloud_file_id",
        "coverFileId",
        "coverUrl",
        "poster_url",
        "posterUrl",
        "poster",
    )

    def item_lineup(item: dict[str, Any]) -> list[Any]:
        value = item.get("lineup") or item.get("lineup_artists") or item.get("lineupItems") or item.get("poster_vl_lineup") or []
        return value if isinstance(value, list) else [value] if has_value(value) else []

    lineup_count = sum(1 for item in items if any_field(item, lineup_keys))
    lineup_ge3_count = sum(1 for item in items if len(item_lineup(item)) >= 3)
    ticket_count = sum(1 for item in items if any_field(item, price_keys))
    time_count = sum(1 for item in items if any_field(item, time_keys))
    poster_evidence_count = sum(1 for item in items if has_value(item.get("poster_selection_evidence") or item.get("posterSelectionEvidence")))
    cloudbase_poster_count = sum(
        1 for item in items if any(str(item.get(key) or "").startswith("cloud://") for key in poster_keys)
    )
    public_poster_count = sum(
        1
        for item in items
        if any(
            "mmbiz" in str(item.get(key) or "")
            or "qpic" in str(item.get(key) or "")
            or str(item.get(key) or "").startswith(("http://", "https://"))
            for key in poster_keys
        )
    )

    metrics = {
        "item_count": item_count,
        "sanji_queue_row_count": gap.get("queue_row_count"),
        "sanji_candidate_event_like_row_count": gap.get("candidate_event_like_row_count"),
        "sanji_matched_row_count": gap.get("matched_row_count"),
        "sanji_missing_row_count": gap.get("missing_row_count"),
        "parent_overview_excluded_count": count_value(gap, "excluded_reason_counts", "parent_overview_excluded"),
        "cloudbase_poster_count": cloudbase_poster_count,
        "public_poster_count": quality.get("public_wechat_or_qpic_poster_count", public_poster_count),
        "poster_evidence_count": poster_evidence_count,
        "main_poster_review_count": quality.get("main_poster_selection_review_required_count"),
        "missing_geo_count": quality.get("missing_geo_count"),
        "lineup_count": lineup_count,
        "lineup_ge3_count": lineup_ge3_count,
        "ticket_count": ticket_count,
        "time_count": time_count,
        "field_hard_fail_count": field_audit.get("hard_fail_count"),
        "underfilled_lineup_review_count": count_value(field_audit, "summary", "underfilled_lineup_review"),
    }
    metrics["llm_cost"] = estimate_llm_cost(context, item_count)
    return metrics


def collect_context(status: dict[str, Any]) -> dict[str, Any]:
    summary_path = discover_publish_summary(status)
    summary = maybe_load(summary_path)
    run_dir = report_dir_from_summary(summary_path)
    cloudrun_path = cloudrun_report_path(summary, summary_path)
    cloudrun = maybe_load(cloudrun_path)
    gap_path = Path(str(summary.get("sanji_queue_package_gap_audit_report") or "")) if summary else None
    gap = maybe_load(gap_path)
    quality = maybe_load(run_dir / "release_package_quality_gate.json" if run_dir else None)
    field_audit = maybe_load(run_dir / "lineup_address_time_audit.json" if run_dir else None)

    context = {
        "status": status,
        "run_dir": str(run_dir) if run_dir else "",
        "summary_path": str(summary_path) if summary_path else "",
        "summary": summary,
        "cloudrun_report_path": str(cloudrun_path) if cloudrun_path else "",
        "cloudrun": cloudrun,
        "gap_report_path": str(gap_path) if gap_path else "",
        "gap": gap,
        "quality": quality,
        "field_audit": field_audit,
        "hermes_tasks": collect_hermes_scheduler_status(),
        "windows_tasks": collect_windows_scheduler_status(),
    }
    context["metrics"] = collect_release_metrics(context)
    return context


def infer_event(status: dict[str, Any], context: dict[str, Any]) -> str:
    summary = context.get("summary") or {}
    quality = context.get("quality") or {}
    decision_text = " ".join(
        str(summary.get(key) or "") for key in ("status", "decision", "blocked_reason")
    ).lower()
    if "blocked" in decision_text:
        return "failure"
    if summary.get("release_ready") is False or summary.get("package_candidate_ready") is False:
        return "failure"
    if quality and quality.get("ok") is False:
        return "failure"
    return "success" if status.get("ok") else "failure"


def backend_not_executed_label(context: dict[str, Any]) -> str:
    status = context.get("status") or {}
    summary = context.get("summary") or {}
    quality = context.get("quality") or {}
    if quality and quality.get("ok") is False:
        return "not_executed_quality_blocked"
    text = " ".join(
        str(value or "")
        for value in (
            summary.get("status"),
            summary.get("decision"),
            summary.get("blocked_reason"),
            summary.get("error"),
            status.get("publish_status"),
            status.get("publish_decision"),
            status.get("error"),
        )
    ).lower()
    if "sanji_queue_package_gap" in text:
        return "not_executed_sanji_gap_blocked"
    if "quality" in text and ("blocked" in text or "hard_failure" in text or "hard_failures" in text):
        return "not_executed_quality_blocked"
    return "not_executed_publish_failed"


def render_message(context: dict[str, Any], event: str) -> tuple[str, str]:
    status = context["status"]
    summary = context["summary"]
    cloudrun = context["cloudrun"]
    gap = context["gap"]
    quality = context["quality"]
    field_audit = context["field_audit"]
    metrics = context.get("metrics") or {}

    decision_text = " ".join(
        str(summary.get(key) or "") for key in ("status", "decision", "blocked_reason")
    ).lower()
    blocked = "blocked" in decision_text
    ok = event == "success" and not blocked and quality.get("ok") is not False
    title = "HUAIDJ 日更发布阻断" if blocked else ("HUAIDJ 日更发布完成" if ok else "HUAIDJ 日更发布失败")
    icon = "BLOCKED" if blocked else ("OK" if ok else "FAIL")

    active_version = (
        count_value(cloudrun, "post_update_server_identity", "active_version")
        or count_value(cloudrun, "operation", "version_name")
        or status.get("cloudrun_revision")
        or ""
    )
    cloudrun_smoke = status.get("cloudrun_smoke_ok")
    if cloudrun_smoke is None:
        cloudrun_smoke = summary.get("cloudrun_smoke_ok")
    if cloudrun_smoke is None and cloudrun:
        cloudrun_smoke = bool(
            count_value(cloudrun, "post_update_server_identity", "active_version")
            or count_value(cloudrun, "operation", "version_name")
        )
    boundary = summary.get("boundary") if isinstance(summary.get("boundary"), dict) else {}
    deploy_requested = bool(summary.get("deploy_backend") or status.get("deploy_backend"))
    deploy_executed = bool(
        summary.get("cloudrun_deploy_executed")
        or boundary.get("cloudrun_deploy_executed")
        or context.get("cloudrun")
    )
    upload_frontend = bool(summary.get("miniprogram_upload_executed") or status.get("upload_frontend"))
    original_failed = (
        summary.get("original_failed_status")
        or status.get("original_failed_stage")
        or ""
    )
    quality_ok = quality.get("ok")
    hard_failures = quality.get("hard_failures", [])
    missing_geo = quality.get("missing_geo_count")
    poster_review = quality.get("main_poster_selection_review_required_count")
    field_hard_fail = field_audit.get("hard_fail_count")
    item_count = int(metrics.get("item_count") or summary.get("item_count") or 0)
    llm_cost = metrics.get("llm_cost") or {}
    if llm_cost.get("exact_available"):
        llm_cost_line = f"成本: {llm_cost.get('cost_cny')} 元 (usage精确)"
        llm_cost_detail_line = (
            "成本明细: "
            f"{llm_cost.get('provider') or summary.get('poster_vl_provider', '')}/"
            f"{llm_cost.get('model') or status.get('poster_vl_model', '')}; "
            f"calls={llm_cost.get('call_count') or 0}; "
            f"input={llm_cost.get('prompt_tokens') or 0}; "
            f"output={llm_cost.get('completion_tokens') or 0}; "
            f"total={llm_cost.get('total_tokens') or 0}"
        )
    else:
        llm_cost_line = f"成本: 约 {llm_cost.get('estimated_range_cny', 'n/a')} 元 (估算)"
        llm_cost_detail_line = (
            "成本明细: "
            f"calls_est={llm_cost.get('call_count_estimate', 0)}; "
            "未记录精确usage"
        )
    scheduler_line = render_hermes_scheduler_status(context.get("hermes_tasks") or [])
    if not scheduler_line:
        scheduler_line = render_scheduler_status(context.get("windows_tasks") or [])
    image_window = status.get("poster_vl_max_images", summary.get("poster_vl_max_images", ""))
    image_window_text = "不限/全图" if str(image_window) == "0" else f"max_images={image_window}"

    lines = [
        f"[{icon}] {title}",
        f"成功: {'是' if ok else '否'} | 时段: {status.get('slot', '')} | 状态: {status.get('stage', '')}",
        "",
        "数据源",
        f"- Sanji导出: {status.get('sanji_exported_rows', '')}",
        (
            "- 候选/命中/缺口: "
            f"{metrics.get('sanji_candidate_event_like_row_count', '')}/"
            f"{metrics.get('sanji_matched_row_count', '')}/"
            f"{metrics.get('sanji_missing_row_count', '')}"
        ),
        (
            "- 模型: "
            f"{summary.get('poster_vl_provider', status.get('poster_vl_provider', 'qwen3_vl'))}/"
            f"{status.get('poster_vl_model', summary.get('poster_vl_model', ''))}"
        ),
        f"- 图片窗口: {image_window_text}",
    ]
    if item_count:
        lines.extend(
            [
                "",
                "发布",
                f"- 活动: {item_count} 条",
                "",
                "海报",
                f"- CloudBase: {rate(int(metrics.get('cloudbase_poster_count') or 0), item_count)}",
                f"- 公网: {metrics.get('public_poster_count', '')}",
                f"- 主图证据: {rate(int(metrics.get('poster_evidence_count') or 0), item_count)}",
                f"- 复核: {metrics.get('main_poster_review_count', poster_review)}",
                "",
                "识别",
                f"- DJ/lineup: {rate(int(metrics.get('lineup_count') or 0), item_count)}",
                f"- 3人以上: {rate(int(metrics.get('lineup_ge3_count') or 0), item_count)}",
                f"- 票价: {rate(int(metrics.get('ticket_count') or 0), item_count)}",
                f"- 时间: {rate(int(metrics.get('time_count') or 0), item_count)}",
            ]
        )
    if active_version or deploy_executed or deploy_requested or cloudrun_smoke is not None:
        smoke_text = "ok" if cloudrun_smoke is True else ("fail" if cloudrun_smoke is False else "unknown")
        version_text = active_version or (backend_not_executed_label(context) if deploy_requested and not deploy_executed else "unknown")
        lines.extend(["", "部署", f"- 后端: {version_text}", f"- deploy/smoke: {deploy_executed}/{smoke_text}"])
    lines.extend(["", "前端", f"- 上传: {upload_frontend}", "- 审核/发布: 未执行"])
    if original_failed and str(original_failed) != str(status.get("stage", "")):
        lines.extend(["", "恢复", f"- {original_failed} -> {status.get('stage', '')}"])
    if gap:
        lines.extend(
            [
                "",
                "父聚合",
                f"- venue一览过滤: {metrics.get('parent_overview_excluded_count', '')}",
                f"- 普通feed污染: {quality.get('parent_overview_in_activity_feed_count', '')}",
            ]
        )
    if quality or field_audit:
        lines.extend(
            [
                "",
                "质量",
                f"- ok: {quality_ok}",
                f"- hard_failures: {len(hard_failures) if isinstance(hard_failures, list) else hard_failures}",
                f"- missing_geo: {missing_geo}",
                f"- poster_review: {poster_review}",
                f"- field_hard_fail: {field_hard_fail}",
            ]
        )
    lines.extend(["", "成本", f"- {llm_cost_line}", f"- {llm_cost_detail_line}"])
    if scheduler_line:
        lines.extend(["", scheduler_line])
    if not ok and status.get("error"):
        lines.extend(["", "错误", f"- {status.get('error')}"])
    return title, "\n".join(str(line).rstrip() for line in lines).strip()


def build_payload(format_name: str, title: str, message: str) -> tuple[bytes, str]:
    fmt = (format_name or "generic").strip().lower()
    if fmt in {"wecom", "wecom_robot", "wechat_work", "work_wechat"}:
        return (
            json.dumps({"msgtype": "text", "text": {"content": message}}, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )
    if fmt in {"serverchan", "server_chan", "serverchan_sendkey"}:
        return urllib.parse.urlencode({"title": title, "desp": message}).encode("utf-8"), "application/x-www-form-urlencoded"
    return (
        json.dumps(
            {
                "source": "huaidj_sanji_daily_publish",
                "title": title,
                "text": message,
                "markdown": message,
            },
            ensure_ascii=False,
        ).encode("utf-8"),
        "application/json; charset=utf-8",
    )


def send(endpoint: str, payload: bytes, content_type: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": content_type, "User-Agent": "huaidj-sanji-publish-notifier/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(4096).decode("utf-8", errors="replace")
        return {"http_status": response.status, "response_excerpt": body[:500]}


def run_openclaw_command(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    command = os.environ.get("HUAIDJ_OPENCLAW_NOTIFY_COMMAND", "openclaw").strip() or "openclaw"
    if command == "openclaw" and os.name == "nt":
        command = shutil.which("openclaw.cmd") or shutil.which("openclaw.exe") or command
    return subprocess.run(
        [command, *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def default_hermes_root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "hermes" / "hermes-agent"


def default_hermes_home() -> Path:
    configured = os.environ.get("HUAIDJ_HERMES_HOME", "").strip()
    if configured:
        return Path(configured)
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "hermes"


def hermes_home_for_root(root: Path) -> Path:
    configured = os.environ.get("HUAIDJ_HERMES_HOME", "").strip()
    if configured:
        return Path(configured)
    if root.name.lower() == "hermes-agent":
        return root.parent
    return default_hermes_home()


def hermes_python(root: Path) -> Path:
    configured = os.environ.get("HUAIDJ_HERMES_PYTHON", "").strip()
    if configured:
        return Path(configured)
    return root / "venv" / "Scripts" / "python.exe" if os.name == "nt" else root / "venv" / "bin" / "python"


def hermes_target() -> tuple[str, str]:
    for key in ("HUAIDJ_HERMES_NOTIFY_TARGET", "HUAIDJ_HERMES_WEIXIN_TARGET"):
        value = os.environ.get(key, "").strip()
        if value:
            return value, f"env:{key}"
    return "telegram", "default:telegram_home_channel"


def hermes_gateway_deliver(home: Path | None = None) -> tuple[str, str]:
    configured = os.environ.get("HUAIDJ_HERMES_GATEWAY_DELIVER", "").strip()
    if configured:
        return configured, "env:HUAIDJ_HERMES_GATEWAY_DELIVER"
    target, target_source = hermes_target()
    return target or "telegram", target_source


def load_hermes_gateway_state(home: Path) -> dict[str, Any]:
    state_path = home / "gateway_state.json"
    payload = maybe_load(state_path)
    platforms = payload.get("platforms") if isinstance(payload.get("platforms"), dict) else {}
    weixin = platforms.get("weixin") if isinstance(platforms.get("weixin"), dict) else {}
    telegram = platforms.get("telegram") if isinstance(platforms.get("telegram"), dict) else {}
    return {
        "state_path": str(state_path),
        "exists": state_path.exists(),
        "gateway_state": str(payload.get("gateway_state") or ""),
        "pid": payload.get("pid"),
        "weixin_state": str(weixin.get("state") or ""),
        "telegram_state": str(telegram.get("state") or ""),
    }


def prepare_hermes_gateway_notification_script(home: Path, message: str) -> tuple[str, Path, Path]:
    safe_id = re.sub(
        r"[^a-zA-Z0-9_-]+",
        "_",
        f"huaidj_notify_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{short_hash(message)}",
    )[:96]
    payload_dir = home / "cron" / "huaidj_notifications"
    script_dir = home / "scripts" / "huaidj_notifications"
    payload_dir.mkdir(parents=True, exist_ok=True)
    script_dir.mkdir(parents=True, exist_ok=True)

    payload_path = payload_dir / f"{safe_id}.json"
    script_path = script_dir / f"{safe_id}.py"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": "huaidj_hermes_gateway_notification_payload.v1",
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "message": message,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    script_path.write_text(
        "\n".join(
            [
                "# Auto-generated by HUAIDJ Sanji publish notifier.",
                "import json",
                "from pathlib import Path",
                f"payload_path = Path({json.dumps(str(payload_path), ensure_ascii=False)})",
                "payload = json.loads(payload_path.read_text(encoding='utf-8'))",
                "print(str(payload.get('message') or '').strip())",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return f"huaidj_notifications/{script_path.name}", payload_path, script_path


def wait_for_hermes_gateway_delivery(home: Path, job_id: str, timeout: int, target: str = "") -> dict[str, Any]:
    log_paths = [home / "logs" / "agent.log", home / "logs" / "gateway.log"]
    deadline = time.time() + max(timeout, 1)
    platform = target.split(":", 1)[0].strip() or "weixin"
    delivered_live = f"Job '{job_id}': delivered to {platform}:"
    standalone = f"Job '{job_id}': delivered to {platform}:"
    last_excerpt = ""
    last_log_path = ""
    while time.time() < deadline:
        for log_path in log_paths:
            if not log_path.exists():
                continue
            try:
                text = log_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                text = ""
            relevant = [line for line in text.splitlines()[-300:] if job_id in line]
            if relevant:
                last_log_path = str(log_path)
                last_excerpt = "\n".join(redact_for_report(line, target) for line in relevant[-8:])
                lowered = last_excerpt.lower()
                if delivered_live in "\n".join(relevant) and "via live adapter" in lowered:
                    return {
                        "delivered": True,
                        "delivery_path": "gateway_live_adapter",
                        "gateway_log_path": str(log_path),
                        "log_paths_checked": [str(path) for path in log_paths],
                        "gateway_log_excerpt": last_excerpt[:1600],
                    }
                if "falling back to standalone" in lowered:
                    return {
                        "delivered": False,
                        "delivery_path": "standalone_fallback_attempted",
                        "gateway_log_path": str(log_path),
                        "log_paths_checked": [str(path) for path in log_paths],
                        "gateway_log_excerpt": last_excerpt[:1600],
                        "error": "gateway live adapter fell back to standalone",
                    }
                if platform == "weixin" and "ilink sendmessage rate limited" in lowered:
                    return {
                        "delivered": False,
                        "delivery_path": "gateway_live_adapter",
                        "gateway_log_path": str(log_path),
                        "log_paths_checked": [str(path) for path in log_paths],
                        "gateway_log_excerpt": last_excerpt[:1600],
                        "error": "weixin iLink rate limited",
                    }
                if standalone in "\n".join(relevant) and "via live adapter" not in lowered:
                    return {
                        "delivered": True,
                        "delivery_path": "gateway_scheduler_delivery",
                        "gateway_log_path": str(log_path),
                        "log_paths_checked": [str(path) for path in log_paths],
                        "gateway_log_excerpt": last_excerpt[:1600],
                        "warning": "Hermes gateway scheduler delivered without live-adapter suffix",
                    }
                if "delivery failed" in lowered or "delivery error" in lowered:
                    return {
                        "delivered": False,
                        "delivery_path": "gateway_live_adapter",
                        "gateway_log_path": str(log_path),
                        "log_paths_checked": [str(path) for path in log_paths],
                        "gateway_log_excerpt": last_excerpt[:1600],
                        "error": "gateway delivery failed",
                    }
        time.sleep(2)
    return {
        "delivered": False,
        "delivery_path": "gateway_live_adapter",
        "gateway_log_path": last_log_path or str(log_paths[0]),
        "log_paths_checked": [str(path) for path in log_paths],
        "gateway_log_excerpt": last_excerpt[:1600],
        "error": f"timed out waiting for Hermes gateway delivery log after {timeout}s",
    }


def send_via_hermes_gateway(
    *,
    title: str,
    message: str,
    dry_run: bool,
    timeout: int,
) -> dict[str, Any]:
    root = Path(os.environ.get("HUAIDJ_HERMES_AGENT_ROOT", "") or default_hermes_root())
    home = hermes_home_for_root(root)
    python = hermes_python(root)
    deliver, deliver_source = hermes_gateway_deliver(home)
    result: dict[str, Any] = {
        "driver": "hermes_gateway",
        "platform": deliver.split(":", 1)[0].strip() or "telegram",
        "root": str(root),
        "home": str(home),
        "python": str(python),
        "deliver_sha256_12": short_hash(deliver),
        "deliver_source": deliver_source,
        "sent": False,
        "skipped_reason": "",
        "error": "",
    }
    if dry_run:
        result["skipped_reason"] = "dry_run"
        return result
    if not root.exists():
        result["error"] = f"hermes root missing: {root}"
        return result
    if not home.exists():
        result["error"] = f"hermes home missing: {home}"
        return result
    if not python.exists():
        result["error"] = f"hermes python missing: {python}"
        return result

    gateway_state = load_hermes_gateway_state(home)
    result["gateway_state"] = gateway_state
    if gateway_state.get("exists") and gateway_state.get("gateway_state") != "running":
        result["error"] = f"Hermes gateway not running: {gateway_state.get('gateway_state') or 'unknown'}"
        return result
    platform_state = gateway_state.get(f"{result['platform']}_state")
    if gateway_state.get("exists") and platform_state and platform_state != "connected":
        result["error"] = f"Hermes {result['platform']} not connected: {platform_state}"
        return result

    script_rel, payload_path, script_path = prepare_hermes_gateway_notification_script(home, message)
    result.update(
        {
            "script_rel": script_rel,
            "payload_path": str(payload_path),
            "script_path": str(script_path),
        }
    )

    code = r'''
import json
import os
import sys
from pathlib import Path

root = Path(os.environ["HUAIDJ_HERMES_AGENT_ROOT_FOR_SEND"])
home = Path(os.environ["HUAIDJ_HERMES_HOME_FOR_SEND"])
script_rel = os.environ["HUAIDJ_HERMES_NOTIFY_SCRIPT_REL"]
deliver = os.environ["HUAIDJ_HERMES_GATEWAY_DELIVER_FOR_SEND"]
job_name = os.environ.get("HUAIDJ_HERMES_NOTIFY_JOB_NAME", "HUAIDJ Sanji publish notification")
sys.path.insert(0, str(root))
os.environ["HERMES_HOME"] = str(home)
from hermes_cli.send_cmd import _load_hermes_env
_load_hermes_env()
from cron.jobs import create_job, trigger_job, update_job
job = create_job(
    prompt=None,
    schedule="1m",
    name=job_name,
    repeat=1,
    deliver=deliver,
    script=script_rel,
    no_agent=True,
)
job = update_job(job["id"], {"wrap_response": False}) or job
triggered = trigger_job(job["id"])
print(json.dumps(
    {
        "ok": True,
        "job_id": job["id"],
        "deliver": job.get("deliver"),
        "next_run_at": (triggered or job).get("next_run_at"),
    },
    ensure_ascii=False,
))
'''
    env = os.environ.copy()
    env["HUAIDJ_HERMES_AGENT_ROOT_FOR_SEND"] = str(root)
    env["HUAIDJ_HERMES_HOME_FOR_SEND"] = str(home)
    env["HUAIDJ_HERMES_NOTIFY_SCRIPT_REL"] = script_rel
    env["HUAIDJ_HERMES_GATEWAY_DELIVER_FOR_SEND"] = deliver
    env["HERMES_HOME"] = str(home)
    try:
        proc = subprocess.run(
            [str(python), "-c", code],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=max(timeout, 30),
            check=False,
            env=env,
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    parsed: dict[str, Any] = {}
    if stdout.strip():
        try:
            parsed = json.loads(stdout.strip().splitlines()[-1])
        except Exception:
            parsed = {}
    result.update(
        {
            "enqueue_exit_code": proc.returncode,
            "stdout_excerpt": redact_for_report(stdout, deliver)[:1200],
            "stderr_excerpt": redact_for_report(stderr, deliver)[:1200],
            "job_id": parsed.get("job_id"),
            "next_run_at": parsed.get("next_run_at"),
        }
    )
    if proc.returncode != 0 or not parsed.get("ok") or not parsed.get("job_id"):
        result["error"] = str(parsed.get("error") or f"hermes gateway enqueue exited with {proc.returncode}")
        return result

    wait_timeout = max(timeout, int(os.environ.get("HUAIDJ_HERMES_GATEWAY_WAIT_SEC", "90") or "90"))
    delivery = wait_for_hermes_gateway_delivery(home, str(parsed["job_id"]), wait_timeout, deliver)
    result["delivery"] = delivery
    if delivery.get("delivered"):
        result["sent"] = True
        return result
    result["error"] = str(delivery.get("error") or "Hermes gateway delivery was not confirmed")
    return result


def send_via_hermes_standalone(
    *,
    title: str,
    message: str,
    dry_run: bool,
    timeout: int,
) -> dict[str, Any]:
    root = Path(os.environ.get("HUAIDJ_HERMES_AGENT_ROOT", "") or default_hermes_root())
    python = hermes_python(root)
    target, target_source = hermes_target()
    result: dict[str, Any] = {
        "driver": "hermes_standalone",
        "platform": target.split(":", 1)[0].strip() or "telegram",
        "root": str(root),
        "python": str(python),
        "target_sha256_12": short_hash(target),
        "target_source": target_source,
        "sent": False,
        "skipped_reason": "",
        "error": "",
    }
    if dry_run:
        result["skipped_reason"] = "dry_run"
        return result
    if not root.exists():
        result["error"] = f"hermes root missing: {root}"
        return result
    if not python.exists():
        result["error"] = f"hermes python missing: {python}"
        return result

    code = r'''
import json
import os
import sys
from pathlib import Path

root = Path(os.environ["HUAIDJ_HERMES_AGENT_ROOT_FOR_SEND"])
target = os.environ["HUAIDJ_HERMES_TARGET_FOR_SEND"]
message = os.environ["HUAIDJ_HERMES_MESSAGE_FOR_SEND"]
sys.path.insert(0, str(root))
from hermes_cli.send_cmd import _load_hermes_env
_load_hermes_env()
from tools.send_message_tool import send_message_tool
raw = send_message_tool({"action": "send", "target": target, "message": message})
try:
    payload = json.loads(raw)
except Exception:
    payload = {"error": "invalid_json_from_hermes_send_message_tool", "raw_excerpt": str(raw)[:300]}
print(json.dumps(payload, ensure_ascii=False))
raise SystemExit(0 if payload.get("success") else 2)
'''
    env = os.environ.copy()
    env["HUAIDJ_HERMES_AGENT_ROOT_FOR_SEND"] = str(root)
    env["HUAIDJ_HERMES_TARGET_FOR_SEND"] = target
    env["HUAIDJ_HERMES_MESSAGE_FOR_SEND"] = message
    try:
        proc = subprocess.run(
            [str(python), "-c", code],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    parsed: dict[str, Any] = {}
    if stdout.strip():
        try:
            parsed = json.loads(stdout.strip().splitlines()[-1])
        except Exception:
            parsed = {}
    result.update(
        {
            "send_exit_code": proc.returncode,
            "stdout_excerpt": redact_for_report(stdout, target)[:1200],
            "stderr_excerpt": redact_for_report(stderr, target)[:1200],
            "result_keys": sorted([key for key in parsed.keys() if key not in {"chat_id", "target", "to", "id", "message_id", "messageId", "note"}]),
            "used_home_channel": "note" in parsed,
        }
    )
    if proc.returncode == 0 and parsed.get("success"):
        result["sent"] = True
        return result
    result["error"] = str(parsed.get("error") or f"hermes exited with {proc.returncode}")
    return result


def classify_openclaw_output(text: str) -> str:
    lowered = text.lower()
    if "needsrelogin" in lowered or "needs relogin" in lowered or "session expired" in lowered:
        return "needs_relogin"
    if (
        re.search(r"status:\s*configured,\s*disabled", lowered)
        or re.search(r"\bchannel\b.*\bdisabled\b", lowered)
        or re.search(r"\bdisabled\b.*\bchannel\b", lowered)
    ):
        return "channel_disabled"
    if "unknown channel" in lowered:
        return "unknown_channel"
    if "not configured" in lowered:
        return "not_configured"
    return ""


def probe_openclaw_channel(channel: str, account: str, timeout: int) -> dict[str, Any]:
    args = ["channels", "capabilities", "--channel", channel]
    if account:
        args.extend(["--account", account])
    proc = run_openclaw_command(args, timeout)
    combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    return {
        "exit_code": proc.returncode,
        "stdout_excerpt": (proc.stdout or "")[:2000],
        "stderr_excerpt": (proc.stderr or "")[:2000],
        "status_hint": classify_openclaw_output(combined),
    }


def discover_openclaw_imessage_target(channel: str, account: str, timeout: int) -> tuple[str, str]:
    """Return (target, source) without exposing the target to logs.

    For this machine the notification account is macbook-bot, whose allowFrom
    list contains the user's iMessage handle. We use that only as an outbound
    target and report a short hash, never the raw handle.
    """

    if channel != "imessage" or not account:
        return "", ""
    proc = run_openclaw_command(
        ["config", "get", f"channels.imessage.accounts.{account}.allowFrom"],
        timeout,
    )
    if proc.returncode != 0:
        return "", ""
    try:
        value = json.loads((proc.stdout or "").strip())
    except json.JSONDecodeError:
        return "", ""
    if isinstance(value, list) and value:
        target = str(value[0]).strip()
    else:
        target = str(value).strip()
    return target, f"openclaw_config:channels.imessage.accounts.{account}.allowFrom[0]" if target else ""


def send_via_openclaw(
    *,
    title: str,
    message: str,
    dry_run: bool,
    timeout: int,
) -> dict[str, Any]:
    channel = os.environ.get("HUAIDJ_OPENCLAW_NOTIFY_CHANNEL", OPENCLAW_DEFAULT_CHANNEL).strip() or OPENCLAW_DEFAULT_CHANNEL
    account = os.environ.get("HUAIDJ_OPENCLAW_NOTIFY_ACCOUNT", OPENCLAW_DEFAULT_ACCOUNT).strip()
    target = os.environ.get("HUAIDJ_OPENCLAW_NOTIFY_TARGET", "").strip()
    target_source = "env:HUAIDJ_OPENCLAW_NOTIFY_TARGET" if target else ""
    if not target:
        target, target_source = discover_openclaw_imessage_target(channel, account, timeout)
    result: dict[str, Any] = {
        "driver": "openclaw",
        "channel": channel,
        "account": account,
        "target_sha256_12": short_hash(target),
        "target_source": target_source,
        "sent": False,
        "skipped_reason": "",
        "error": "",
    }
    if not target:
        result["skipped_reason"] = "missing_openclaw_target_env"
        return result

    try:
        probe = probe_openclaw_channel(channel, account, timeout)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    result["channel_probe"] = probe
    if probe.get("status_hint") in {"needs_relogin", "channel_disabled", "not_configured"}:
        result["skipped_reason"] = f"openclaw_{probe['status_hint']}"
        return result

    args = ["message", "send", "--channel", channel]
    if account:
        args.extend(["--account", account])
    args.extend(["--target", target, "--message", message, "--json"])
    if dry_run:
        args.append("--dry-run")

    try:
        proc = run_openclaw_command(args, timeout)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    result.update(
        {
            "send_exit_code": proc.returncode,
            "stdout_excerpt": redact_for_report(proc.stdout or "", target)[:2000],
            "stderr_excerpt": redact_for_report(proc.stderr or "", target)[:2000],
            "status_hint": classify_openclaw_output(combined),
        }
    )
    if dry_run and proc.returncode == 0:
        result["skipped_reason"] = "dry_run"
        return result
    if proc.returncode == 0:
        result["sent"] = True
        return result
    result["error"] = result.get("status_hint") or f"openclaw exited with {proc.returncode}"
    return result


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status-json", required=True)
    parser.add_argument("--event", choices=["success", "failure", "auto"], default="auto")
    parser.add_argument("--report-json", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout-sec", type=int, default=30)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    status_path = Path(args.status_json)
    status = load_json(status_path)
    context = collect_context(status)
    event = args.event
    if event == "auto":
        event = infer_event(status, context)

    title, message = render_message(context, event)
    driver = os.environ.get("HUAIDJ_WECHAT_NOTIFY_DRIVER", "auto").strip().lower() or "auto"
    env_key, endpoint = first_existing_env()
    notify_format = os.environ.get("HUAIDJ_WECHAT_NOTIFY_FORMAT", os.environ.get("HUAIDJ_NOTIFY_FORMAT", "generic"))
    report_path = Path(args.report_json) if args.report_json else status_path.with_name("wechat_publish_notification.json")

    report = {
        "schema_version": "huaidj_sanji_publish_wechat_notification.v2",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status_json": str(status_path),
        "event": event,
        "title": title,
        "message": message,
        "driver": driver,
        "endpoint_env_key": env_key,
        "endpoint_sha256_12": short_hash(endpoint),
        "format": notify_format,
        "dry_run": bool(args.dry_run),
        "sent": False,
        "skipped_reason": "",
        "error": "",
        "context_paths": {
            "summary_path": context.get("summary_path", ""),
            "cloudrun_report_path": context.get("cloudrun_report_path", ""),
            "gap_report_path": context.get("gap_report_path", ""),
        },
        "metrics": context.get("metrics", {}),
    }

    if driver in {"auto", "hermes", "hermes_gateway", "hermes-gateway", "hermes-weixin", "weixin"}:
        hermes_result = send_via_hermes_gateway(
            title=title,
            message=message,
            dry_run=args.dry_run,
            timeout=args.timeout_sec,
        )
        report["hermes"] = hermes_result
        if hermes_result.get("sent"):
            report["sent"] = True
            report["notify_driver"] = "hermes_gateway"
            write_report(report_path, report)
            print(json.dumps(report, ensure_ascii=False))
            return 0
        if args.dry_run and hermes_result.get("skipped_reason") == "dry_run":
            report["skipped_reason"] = "dry_run"
            report["notify_driver"] = "hermes_gateway"
            write_report(report_path, report)
            print(json.dumps(report, ensure_ascii=False))
            return 0
        if driver in {"hermes", "hermes_gateway", "hermes-gateway", "hermes-weixin", "weixin"}:
            report["skipped_reason"] = str(hermes_result.get("skipped_reason") or "")
            report["error"] = str(hermes_result.get("error") or "")
            write_report(report_path, report)
            print(json.dumps(report, ensure_ascii=False))
            return 0 if report["skipped_reason"] else 2

    if driver in {"hermes_standalone", "hermes-standalone"}:
        hermes_result = send_via_hermes_standalone(
            title=title,
            message=message,
            dry_run=args.dry_run,
            timeout=args.timeout_sec,
        )
        report["hermes"] = hermes_result
        if hermes_result.get("sent"):
            report["sent"] = True
            report["notify_driver"] = "hermes_standalone"
            write_report(report_path, report)
            print(json.dumps(report, ensure_ascii=False))
            return 0
        if args.dry_run and hermes_result.get("skipped_reason") == "dry_run":
            report["skipped_reason"] = "dry_run"
            report["notify_driver"] = "hermes_standalone"
            write_report(report_path, report)
            print(json.dumps(report, ensure_ascii=False))
            return 0
        report["skipped_reason"] = str(hermes_result.get("skipped_reason") or "")
        report["error"] = str(hermes_result.get("error") or "")
        write_report(report_path, report)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["skipped_reason"] else 2

    allow_imessage_fallback = os.environ.get("HUAIDJ_ALLOW_IMESSAGE_FALLBACK", "").strip().lower() in {"1", "true", "yes", "on"}
    if driver in {"openclaw", "openclaw-imessage", "imessage", "openclaw-weixin"} or (driver == "auto" and allow_imessage_fallback):
        openclaw_result = send_via_openclaw(
            title=title,
            message=message,
            dry_run=args.dry_run,
            timeout=args.timeout_sec,
        )
        report["openclaw"] = openclaw_result
        if openclaw_result.get("sent"):
            report["sent"] = True
            report["notify_driver"] = "openclaw"
            write_report(report_path, report)
            print(json.dumps(report, ensure_ascii=False))
            return 0
        if args.dry_run and openclaw_result.get("skipped_reason") == "dry_run":
            report["skipped_reason"] = "dry_run"
            report["notify_driver"] = "openclaw"
            write_report(report_path, report)
            print(json.dumps(report, ensure_ascii=False))
            return 0
        if driver in {"openclaw", "openclaw-imessage", "imessage", "openclaw-weixin", "weixin"}:
            report["skipped_reason"] = str(openclaw_result.get("skipped_reason") or "")
            report["error"] = str(openclaw_result.get("error") or "")
            write_report(report_path, report)
            print(json.dumps(report, ensure_ascii=False))
            return 0 if report["skipped_reason"] else 2

    if not endpoint:
        report["skipped_reason"] = "missing_endpoint_env"
        write_report(report_path, report)
        print(json.dumps(report, ensure_ascii=False))
        return 0

    payload, content_type = build_payload(notify_format, title, message)
    if args.dry_run:
        report["skipped_reason"] = "dry_run"
        report["payload_bytes"] = len(payload)
        write_report(report_path, report)
        print(json.dumps(report, ensure_ascii=False))
        return 0

    try:
        result = send(endpoint, payload, content_type, args.timeout_sec)
        report.update(result)
        report["sent"] = True
        report["notify_driver"] = "webhook"
        write_report(report_path, report)
        print(json.dumps(report, ensure_ascii=False))
        return 0
    except Exception as exc:  # best-effort notification; caller should not fail publish
        report["error"] = f"{type(exc).__name__}: {exc}"
        write_report(report_path, report)
        print(json.dumps(report, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
