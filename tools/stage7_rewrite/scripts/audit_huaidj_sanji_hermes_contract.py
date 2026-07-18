#!/usr/bin/env python3
"""Read-only audit for the HUAIDJ Sanji Hermes cheap weekly execution contract.

This script intentionally does not start Sanji, call Qwen, deploy CloudRun, send
Weixin messages, or mutate scheduler state. It checks that execution authority is
not split across Hermes, Windows Task Scheduler, and Codex automation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[3]
DEFAULT_HERMES_HOME = Path(r"F:\DevData\Hermes")
DEFAULT_HERMES_AGENT = DEFAULT_HERMES_HOME / "hermes-agent"
CODEX_AUTOMATION = Path.home() / ".codex" / "automations" / "weekly-daily-incremental-18" / "automation.toml"
SKILL_PATH = Path.home() / ".codex" / "skills" / "huaidj-weekly-pipeline" / "SKILL.md"
FORBIDDEN_SANJI_SOURCE_CLAIMS = (
    "Sanji direct RSS package remained the source of truth",
    "direct_rss_feed_fetch=true",
    "sanji_direct_rss_feed_fetch=true",
)
FORBIDDEN_DOC_CLAIMS = (
    "This is the active production contract after the 2026-06-30 cadence update.",
    "Friday `16:10`: catches late weekend posts",
)
STALE_HERMES_HOME_PATTERN = re.compile(
    r"Hermes root defaults to\s+`C:\\Users\\pc\\AppData\\Local\\hermes\\hermes-agent`",
    re.MULTILINE,
)


def resolve_hermes_runtime_root() -> Path:
    configured = os.environ.get("HERMES_DESKTOP_HERMES_ROOT", "").strip()
    if not configured and os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                configured = str(winreg.QueryValueEx(key, "HERMES_DESKTOP_HERMES_ROOT")[0] or "").strip()
        except (FileNotFoundError, OSError):
            configured = ""
    return Path(configured) if configured else DEFAULT_HERMES_AGENT

EXPECTED_HERMES_JOBS = {
    "HUAIDJ Atlas v2 Sanji Import Nightly": {
        "schedule_expr": "40 23 * * *",
        "script": "huaidj/atlas_v2_sanji_import_nightly.py",
        "deliver": "telegram",
    },
    "HUAIDJ Sanji Wed 21:10": {
        "schedule_expr": "10 21 * * 3",
        "script": "huaidj/sanji_publish_afternoon.py",
        "deliver": "telegram",
    },
    "HUAIDJ Sanji Fri 20:10": {
        "schedule_expr": "10 20 * * 5",
        "script": "huaidj/sanji_publish_afternoon.py",
        "deliver": "telegram",
    },
    "HUAIDJ Sanji RSS Fast Watch": {
        "schedule_expr": "*/30 8-23 * * *",
        "script": "huaidj/sanji_rss_fast_watch.py",
        "deliver": "telegram",
    },
    "HUAIDJ Sanji 登录授权提醒": {
        "schedule_expr": "every 2880m",
        "script": "huaidj/sanji_login_reminder.py",
        "deliver": "telegram",
    },
    "HUAIDJ Coverage Audit Wed 22:40": {
        "schedule_expr": "40 22 * * 3",
        "script": "huaidj/audit_coverage_gap.py",
        "deliver": "telegram",
    },
    "HUAIDJ Coverage Audit Fri 21:40": {
        "schedule_expr": "40 21 * * 5",
        "script": "huaidj/audit_coverage_gap.py",
        "deliver": "telegram",
    },
    "HUAIDJ 全栈健康检查": {
        "schedule_expr": "every 60m",
        "script": "huaidj/health_check.py",
        "deliver": "telegram",
    },
    "HUAIDJ 活动包/API TG Monitor": {
        "schedule_expr": "every 30m",
        "script": "huaidj/package_api_tg_status.py",
        "deliver": "telegram",
    },
}

ALLOWED_EXTRA_HERMES_JOBS: set[str] = set()

LEGACY_ALLOWED_PAUSED_HERMES_JOBS = {
    "HUAIDJ Sanji Publish Noon",
    "HUAIDJ Sanji Publish Evening",
    "HUAIDJ Sanji Fri 16:10",
    "HUAIDJ Coverage Audit Fri 17:40",
    "HUAIDJ Sanji Wed+Fri 14:30",
    "HUAIDJ Coverage Audit (post-pipeline)",
}

EXPECTED_HERMES_SCRIPTS = {
    "huaidj/atlas_v2_sanji_import_nightly.py": (
        "run_atlas_v2_sanji_import.py",
        "--articles-root",
        "SANJI_HOT_ARTICLES_ROOT",
        "rapidocr_onnxruntime",
        "ATLAS_RUN_ID",
        "RUN_LIMIT = 0",
        "MAX_COST_RMB = 15.0",
        "--advance-checkpoint",
        "HUAIDJ_PYTHON",
        "CREATE_NO_WINDOW",
        "subprocess.run(",
        "msvcrt.locking(",
        "atlas_v2_import_lock.v4",
        "return result_code",
        "No production promotion or service restart",
    ),
    "huaidj/sanji_publish_afternoon.py": (
        "pwsh.exe",
        "run_sanji_desktop_recent_export.ps1",
        "run_huaidj_sanji_daily_twice.ps1",
        "-Slot",
        "manual",
        "-SkipSanjiExport",
        "PosterVlMaxImages",
        '"0"',
        "HUAIDJ_REPO",
        "CREATE_NO_WINDOW",
        "subprocess.run(",
        "return result_code",
        "online activity publish completed",
    ),
    "huaidj/sanji_rss_fast_watch.py": (
        "pwsh.exe",
        "run_huaidj_sanji_rss_fast_watch.ps1",
        "-DetectOnly",
    ),
    "huaidj/audit_coverage_gap.py": ("Wed 21:10 + Fri 20:10", "hours=20, minutes=10"),
    "huaidj/health_check.py": (
        "CloudRun API",
        "data-freshness",
        "report_huaidj_package_api_tg_status.py",
        "return int(result.returncode)",
    ),
    "huaidj/sanji_login_reminder.py": ("公众号登录授权提醒", "2 天", "cookie", "token"),
    "huaidj/package_api_tg_status.py": (
        "report_huaidj_package_api_tg_status.py",
        ".package_api_tg_state.json",
        "huaidj_package_api_tg_status",
        "return int(result.returncode)",
    ),
}

FORBIDDEN_HERMES_SCRIPT_TOKENS = {
    "huaidj/sanji_publish_afternoon.py": ("subprocess.Popen(", "[LAUNCHED]", "detached runner"),
    "huaidj/atlas_v2_sanji_import_nightly.py": ("subprocess.Popen(", "[LAUNCHED]", "Runs detached"),
    "huaidj/package_api_tg_status.py": ('"py",', '"-3",'),
}

WINDOWS_TASKS = [
    "HUAIDJ Sanji Daily Publish Evening",
    "HUAIDJ Sanji Daily Publish Noon",
    "HUAIDJ Sanji Desktop Export Evening",
    "HUAIDJ Sanji Desktop Export Noon",
    "HUAIDJ Sanji RSS Fast Watch",
]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8-sig")


def add(checks: list[dict[str, Any]], name: str, ok: bool, detail: str, severity: str = "fail") -> None:
    status = "ok" if ok else severity
    checks.append({"name": name, "status": status, "detail": detail})


def file_contains(path: Path, needles: list[str]) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing: {path}"
    text = read_text(path)
    missing = [needle for needle in needles if needle not in text]
    if missing:
        return False, "missing tokens: " + ", ".join(missing)
    return True, "matched"


def audit_wrappers(checks: list[dict[str, Any]]) -> None:
    wrapper_checks = {
        REPO / "tools/stage7_rewrite/run_huaidj_sanji_daily_twice.ps1": [
            '[string]$PosterExtractionMode = "vl_direct_qwen"',
            '[int]$PosterVlMaxImages = 0',
            '[string]$PosterVlModel = "qwen3.6-plus"',
            '$env:HUAIDJ_WECHAT_NOTIFY_DRIVER = "hermes_gateway"',
            "Remove-Item Env:HUAIDJ_ALLOW_IMESSAGE_FALLBACK",
            "huaidj_sanji_daily_publish.lock",
            "SkipSanjiExport",
            "sanji_db_snapshot_export",
            "direct_rss_feed_fetch must stay false",
        ],
        REPO / "tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs": [
            "isExistingTaskError",
            "already_running",
            "waitForIdle",
        ],
        REPO / "tools/stage7_rewrite/run_huaidj_sanji_rss_fast_watch.ps1": [
            '[int]$PosterVlMaxImages = 0',
            '[string]$PosterVlModel = "qwen3.6-plus"',
            "huaidj_sanji_rss_fast_watch.lock",
            "RecentPublishCooldownMinutes",
            "skip_recent_successful_publish_cooldown",
            "skip_deepseek_peak_pricing_window",
            "09:00-12:00",
            "14:00-18:00",
            "& pwsh -NoProfile",
            "& pwsh @publishArgs",
        ],
        REPO / "tools/stage7_rewrite/run_openclaw_weekly_daily_publish.ps1": [
            '[string]$PosterExtractionMode = "vl_direct_qwen"',
            '[int]$PosterVlMaxImages = 0',
            '[string]$PosterVlModel = "qwen3.6-plus"',
            "sanji_desktop_rss",
        ],
        REPO / "tools/stage7_rewrite/scripts/install_huaidj_sanji_hermes_jobs.py": [
            "HUAIDJ Sanji Wed 21:10",
            "HUAIDJ Sanji Fri 20:10",
            "HUAIDJ Sanji 登录授权提醒",
            "HUAIDJ 活动包/API TG Monitor",
            "10 21 * * 3",
            "10 20 * * 5",
            "*/30 8-23 * * *",
            "every 2880m",
            "every 30m",
            "huaidj/sanji_publish_afternoon.py",
            "huaidj/sanji_login_reminder.py",
            "huaidj/package_api_tg_status.py",
            '"deliver": "telegram"',
            "run_sanji_desktop_recent_export.ps1",
            "vl_direct_qwen",
            "-SkipSanjiExport",
            "-DetectOnly",
            "LEGACY_JOB_NAMES",
        ],
        REPO / "tools/stage7_rewrite/scripts/enrich_weekly_activity_pack_with_qwen_vl.py": [
            "DEFAULT_MAX_IMAGES = 0",
            "if max_images <= 0:",
            "return items",
        ],
        REPO / "tools/stage7_rewrite/scripts/send_sanji_publish_wechat_notification.py": [
            "hermes_gateway",
            "HUAIDJ_ALLOW_IMESSAGE_FALLBACK",
            "wrap_response",
        ],
    }
    for path, needles in wrapper_checks.items():
        ok, detail = file_contains(path, needles)
        add(checks, f"wrapper contract: {path.name}", ok, detail)

    scheduled_export = REPO / "tools/stage7_rewrite/run_sanji_desktop_recent_export.ps1"
    scheduled_export_text = read_text(scheduled_export)
    add(
        checks,
        "Sanji scheduled export never rewrites bundled club overview seed",
        "OverviewMiniProgramJsPath" not in scheduled_export_text
        and '"--out-js"' not in scheduled_export_text,
        "scheduled output must remain under SANJI_EXPORT_OUT_ROOT",
    )

    rss_watch = REPO / "tools/stage7_rewrite/run_huaidj_sanji_rss_fast_watch.ps1"
    rss_watch_text = read_text(rss_watch) if rss_watch.is_file() else ""
    add(
        checks,
        "RSS watcher derives current repo root",
        "$PSScriptRoot" in rss_watch_text
        and r'C:\code\githubstar\wechathtmldownload' not in rss_watch_text,
        "dynamic_repo_root=true"
        if "$PSScriptRoot" in rss_watch_text
        and r'C:\code\githubstar\wechathtmldownload' not in rss_watch_text
        else "hardcoded_or_missing_repo_root",
    )
    installer = REPO / "tools/stage7_rewrite/scripts/install_huaidj_sanji_hermes_jobs.py"
    if installer.exists():
        text = read_text(installer)
        legacy_job_specs = re.findall(r'"HUAIDJ Sanji Publish (?:Noon|Evening)"\s*:\s*{', text)
        add(
            checks,
            "Hermes installer has no active legacy noon/evening job specs",
            not legacy_job_specs,
            "legacy_specs=" + str(len(legacy_job_specs)),
        )

    publish_wrapper = REPO / "tools/stage7_rewrite/run_openclaw_weekly_daily_publish.ps1"
    weekly_pipeline = REPO / "tools/stage7_rewrite/weekly_activity_next_week_pipeline.ps1"
    queue_builder = REPO / "tools/stage7_rewrite/scripts/build_weekly_activity_queue_from_downloads.py"
    freshness_preflight = REPO / "tools/stage7_rewrite/scripts/build_weekly_exporter_freshness_preflight.py"
    refresh_validator = REPO / "tools/stage7_rewrite/scripts/validate_weekly_daily_queue_refresh.py"
    main_poster_review_queue = REPO / "tools/stage7_rewrite/scripts/build_weekly_main_poster_mimo_review_queue.py"
    prefect_flow = REPO / "tools/stage7_rewrite/prefect/huaidj_weekly_flow.py"
    ticket_eval = REPO / "tools/stage7_rewrite/scripts/evaluate_weekly_ticketing_strategies.mjs"
    ok, detail = file_contains(
        publish_wrapper,
        [
            "$SanjiLatestQueuePath",
            "$SanjiLatestSummaryPath",
            "E:\\weekly_activity_pipeline\\longrun",
            '$Longrun = "E:\\weekly_activity_pipeline\\longrun"',
            '$sourceMaterialQueuePaths = if ($SourceMode -eq "sanji_desktop_rss")',
            '$latestQueueSummaryPath = if ($SourceMode -eq "sanji_desktop_rss")',
        ],
    )
    add(checks, "Sanji publish wrapper stays on E drive", ok, detail)
    for path in (publish_wrapper, weekly_pipeline):
        if path.exists():
            text = read_text(path)
            stale = r"D:\downstream_results\stage7_rewrite\longrun" in text
            add(
                checks,
                f"no D longrun default remains: {path.name}",
                not stale,
                "stale_d_longrun_present=" + str(stale).lower(),
            )
    ok, detail = file_contains(
        weekly_pipeline,
        [
            '$LONGRUN = "E:\\weekly_activity_pipeline\\longrun"',
            "E:\\weekly_activity_pipeline\\longrun",
            '$SANJI_OVERVIEW_PREFETCH_JSON = "$SANJI_LATEST_EXPORT_ROOT\\latest_club_overviews.json"',
            "Step 4.1: Attach club overview online artifact",
            '"$API_DIR\\club_overviews.json"',
        ],
    )
    add(checks, "Sanji weekly pipeline outputs stay on E drive", ok, detail)
    weekly_text = read_text(weekly_pipeline)
    add(
        checks,
        "Sanji pipeline never rewrites bundled club overview seed",
        "SANJI_OVERVIEW_MINIPROGRAM_JS" not in weekly_text
        and "apps\\weekly_activity_miniprogram\\data\\club_overviews.js" not in weekly_text,
        "scheduled output must remain an online release artifact",
    )
    e_default_checks = {
        queue_builder: [
            r"E:\weekly_activity_pipeline\longrun\LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE",
            "/mnt/e/weekly_activity_pipeline/longrun/LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE",
        ],
        freshness_preflight: [
            r"E:\weekly_activity_pipeline\longrun\LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE\summary.json",
        ],
        refresh_validator: [
            r"E:\weekly_activity_pipeline\longrun\LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE\summary.json",
        ],
        main_poster_review_queue: [
            "E:/weekly_activity_pipeline/longrun/weekly_poster_cloudbase_cache",
        ],
        prefect_flow: [
            r"E:\weekly_activity_pipeline\longrun",
        ],
        ticket_eval: [
            r"E:\\weekly_activity_pipeline\\longrun\\LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE\\latest_queue.jsonl",
        ],
    }
    for path, needles in e_default_checks.items():
        ok, detail = file_contains(path, list(needles))
        add(checks, f"current longrun default stays on E drive: {path.name}", ok, detail)
        if path.exists():
            text = read_text(path)
            stale = r"D:\downstream_results\stage7_rewrite\longrun" in text
            add(
                checks,
                f"no D longrun default remains: {path.name}",
                not stale,
                "stale_d_longrun_present=" + str(stale).lower(),
            )
    if weekly_pipeline.exists():
        stale_mnt_d_hint = "/mnt/d/downstream_results/stage7_rewrite/longrun/WEEKLY_ACTIVITY_MINIPROGRAM_RELEASE"
        text = read_text(weekly_pipeline)
        add(
            checks,
            "Sanji weekly pipeline has no stale /mnt/d publish hint",
            stale_mnt_d_hint not in text,
            "stale_hint_present=" + str(stale_mnt_d_hint in text).lower(),
        )


def audit_docs(checks: list[dict[str, Any]]) -> None:
    docs = {
        REPO / "docs/SANJI_DAILY_TWO_A_DAY_AUTOMATION_RUNBOOK_20260620.md": [
            "Hermes desktop cron is the authority",
            "PosterVlMaxImages=0",
            "iLink sendmessage rate limited",
        ],
        REPO / "docs/SANJI_DESKTOP_DAILY_PIPELINE_INTEGRATION.md": [
            "qwen3.6-plus",
            "--max-images 0",
            "A run showing",
        ],
        REPO / "docs/current-runtime.md": [
            "Sanji VL Image Window Set To Unlimited",
            "Hermes desktop cron",
            "single wall-clock",
            "PosterVlMaxImages=0",
        ],
        REPO / "docs/HUAIDJ_SANJI_HERMES_WEEKLY_CHEAP_PLAN_20260629.md": [
            "Superseded on 2026-07-05",
            "HUAIDJ Sanji Fri 20:10",
            "HUAIDJ Coverage Audit Fri 21:40",
            "Friday `16:10` / `17:40` jobs must remain paused",
        ],
        SKILL_PATH: [
            "Hermes Gateway is the wall-clock executor",
            "PosterVlMaxImages=0",
            "Never store or print API keys",
            r"F:\DevData\Hermes\cron\jobs.json",
        ],
    }
    for path, needles in docs.items():
        ok, detail = file_contains(path, needles)
        add(checks, f"doc/skill contract: {path.name}", ok, detail)
        if path.exists():
            text = read_text(path)
            hits = [claim for claim in FORBIDDEN_SANJI_SOURCE_CLAIMS if claim in text]
            add(
                checks,
                f"doc stale Sanji source claims absent: {path.name}",
                not hits,
                "hits=" + ", ".join(hits),
            )
            doc_hits = [claim for claim in FORBIDDEN_DOC_CLAIMS if claim in text]
            add(
                checks,
                f"doc stale production contract claims absent: {path.name}",
                not doc_hits,
                "hits=" + ", ".join(doc_hits),
            )
            stale_hermes_home = bool(STALE_HERMES_HOME_PATTERN.search(text))
            add(
                checks,
                f"doc Hermes home is not agent root: {path.name}",
                not stale_hermes_home,
                "stale_hermes_agent_home=" + str(stale_hermes_home).lower(),
            )


def load_hermes_jobs(hermes_home: Path, hermes_agent: Path) -> tuple[list[dict[str, Any]], str]:
    sys.path.insert(0, str(hermes_agent))
    os.environ.setdefault("HERMES_HOME", str(hermes_home))
    try:
        from cron.jobs import load_jobs  # type: ignore
    except Exception as exc:
        return [], f"cannot import Hermes cron.jobs: {exc}"
    try:
        return list(load_jobs()), ""
    except Exception as exc:
        return [], f"cannot load Hermes jobs: {exc}"


def schedule_expr(job: dict[str, Any]) -> str:
    schedule = job.get("schedule")
    if isinstance(schedule, dict):
        return str(schedule.get("expr") or schedule.get("display") or "")
    return str(schedule or "")


def audit_hermes_runtime(checks: list[dict[str, Any]], hermes_home: Path, hermes_agent: Path) -> None:
    """Verify the Windows Desktop/Gateway substrate that actually executes cron.

    The Desktop UI and the Gateway are separate processes.  A valid jobs.json
    is not sufficient when the managed Desktop install, user environment, login
    item, or live Gateway ticker is missing.
    """

    desktop_exe = hermes_agent / "apps" / "desktop" / "release" / "win-unpacked" / "Hermes.exe"
    hermes_python = hermes_agent / "venv" / "Scripts" / "python.exe"
    venv_scripts = hermes_agent / "venv" / "Scripts"
    gateway_cmd = hermes_home / "gateway-service" / "Hermes_Gateway.cmd"
    gateway_vbs = hermes_home / "gateway-service" / "Hermes_Gateway.vbs"
    appdata = Path(os.environ.get("APPDATA", ""))
    startup_vbs = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Hermes_Gateway.vbs"
    start_menu_link = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Hermes.lnk"
    desktop_link = Path.home() / "Desktop" / "Hermes.lnk"

    add(checks, "Hermes managed Desktop installed", desktop_exe.is_file(), str(desktop_exe))
    add(checks, "Hermes CLI runtime installed", hermes_python.is_file(), str(hermes_python))
    add(checks, "Hermes Desktop Start Menu shortcut", start_menu_link.is_file(), str(start_menu_link))
    add(checks, "Hermes Desktop shortcut", desktop_link.is_file(), str(desktop_link))

    runtime_commit = ""
    runtime_clean = False
    runtime_commit_detail = f"missing Git worktree: {hermes_agent}"
    if (hermes_agent / ".git").exists():
        try:
            commit_result = subprocess.run(
                ["git", "-C", str(hermes_agent), "rev-parse", "HEAD"],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=15,
            )
            if commit_result.returncode == 0:
                runtime_commit = commit_result.stdout.strip()
                runtime_commit_detail = f"commit={runtime_commit[:12]}"
                status_result = subprocess.run(
                    ["git", "-C", str(hermes_agent), "status", "--porcelain", "--untracked-files=all"],
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=30,
                )
                dirty_rows = [row for row in status_result.stdout.splitlines() if row.strip()]
                runtime_clean = status_result.returncode == 0 and not dirty_rows
                runtime_commit_detail += f" clean={runtime_clean} dirty_rows={len(dirty_rows)}"
            else:
                runtime_commit_detail = commit_result.stderr.strip()
        except Exception as exc:
            runtime_commit_detail = str(exc)
    add(checks, "Hermes immutable runtime Git commit", len(runtime_commit) >= 7, runtime_commit_detail)
    add(checks, "Hermes immutable runtime Git worktree clean", runtime_clean, runtime_commit_detail)

    user_home = ""
    user_path = ""
    user_runtime = ""
    user_huaidj_python = ""
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
                try:
                    user_home = str(winreg.QueryValueEx(key, "HERMES_HOME")[0] or "")
                except FileNotFoundError:
                    user_home = ""
                try:
                    user_path = str(winreg.QueryValueEx(key, "Path")[0] or "")
                except FileNotFoundError:
                    user_path = ""
                try:
                    user_runtime = str(winreg.QueryValueEx(key, "HERMES_DESKTOP_HERMES_ROOT")[0] or "")
                except FileNotFoundError:
                    user_runtime = ""
                try:
                    user_huaidj_python = str(winreg.QueryValueEx(key, "HUAIDJ_PYTHON")[0] or "")
                except FileNotFoundError:
                    user_huaidj_python = ""
        except Exception as exc:
            add(checks, "Hermes Windows user environment readable", False, str(exc))
    else:
        user_home = os.environ.get("HERMES_HOME", "")
        user_path = os.environ.get("PATH", "")
        user_runtime = os.environ.get("HERMES_DESKTOP_HERMES_ROOT", "")
        user_huaidj_python = os.environ.get("HUAIDJ_PYTHON", "")

    normalized_path_entries = {
        os.path.normcase(os.path.normpath(entry.strip()))
        for entry in user_path.split(os.pathsep)
        if entry.strip()
    }
    expected_home = os.path.normcase(os.path.normpath(str(hermes_home)))
    expected_venv = os.path.normcase(os.path.normpath(str(venv_scripts)))
    add(
        checks,
        "Hermes user HERMES_HOME",
        os.path.normcase(os.path.normpath(user_home)) == expected_home if user_home else False,
        f"value={user_home or '<missing>'} expected={hermes_home}",
    )
    add(
        checks,
        "Hermes venv on user PATH",
        expected_venv in normalized_path_entries,
        f"expected_entry={venv_scripts}",
    )
    add(
        checks,
        "Hermes Desktop immutable runtime root",
        os.path.normcase(os.path.normpath(user_runtime))
        == os.path.normcase(os.path.normpath(str(hermes_agent)))
        if user_runtime
        else False,
        f"value={user_runtime or '<missing>'} expected={hermes_agent}",
    )
    huaidj_python = Path(user_huaidj_python) if user_huaidj_python else Path()
    add(
        checks,
        "HUAIDJ dedicated Python configured",
        bool(user_huaidj_python) and huaidj_python.is_file(),
        f"value={user_huaidj_python or '<missing>'}",
    )
    dependency_ok = False
    dependency_detail = "HUAIDJ_PYTHON missing"
    if user_huaidj_python and huaidj_python.is_file():
        try:
            dependency_result = subprocess.run(
                [
                    str(huaidj_python),
                    "-c",
                    "import bs4,lxml,openai,pydantic,rapidocr_onnxruntime,requests",
                ],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=45,
            )
            dependency_ok = dependency_result.returncode == 0
            dependency_detail = (
                "imports=ok"
                if dependency_ok
                else (dependency_result.stderr or dependency_result.stdout).strip()[-1000:]
            )
        except Exception as exc:
            dependency_detail = str(exc)
    add(checks, "HUAIDJ Python dependency contract", dependency_ok, dependency_detail)

    launcher_ok = gateway_cmd.is_file() and gateway_vbs.is_file()
    launcher_detail = f"cmd={gateway_cmd.is_file()} vbs={gateway_vbs.is_file()}"
    if launcher_ok:
        login_text = read_text(gateway_cmd) + "\n" + read_text(gateway_vbs)
        required = [str(hermes_home), str(hermes_agent), "gateway run"]
        missing = [token for token in required if token not in login_text]
        launcher_ok = not missing
        launcher_detail += " missing=" + ", ".join(missing)
    add(checks, "Hermes Gateway launcher contract", launcher_ok, launcher_detail)
    add(
        checks,
        "Legacy Hermes Startup launcher absent",
        not startup_vbs.exists(),
        f"startup={startup_vbs.exists()} path={startup_vbs}",
    )

    scheduled_task_ok = False
    scheduled_task_detail = "Hermes_Gateway task not queried"
    if os.name == "nt":
        task_script = r"""
$task = Get-ScheduledTask -TaskName 'Hermes_Gateway' -ErrorAction SilentlyContinue
if ($null -eq $task) { exit 3 }
$action = $task.Actions | Select-Object -First 1
[pscustomobject]@{
  State = [string]$task.State
  Execute = [string]$action.Execute
  Arguments = [string]$action.Arguments
} | ConvertTo-Json -Compress
"""
        try:
            task_result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", task_script],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=30,
            )
            if task_result.returncode == 0:
                task_payload = json.loads(task_result.stdout)
                task_state = str(task_payload.get("State") or "")
                task_execute = str(task_payload.get("Execute") or "")
                task_arguments = str(task_payload.get("Arguments") or "")
                scheduled_task_ok = (
                    task_state in {"Running", "Ready"}
                    and "wscript" in task_execute.lower()
                    and str(gateway_vbs) in task_arguments
                )
                scheduled_task_detail = (
                    f"state={task_state} execute={task_execute} vbs_arg={str(gateway_vbs) in task_arguments}"
                )
            else:
                scheduled_task_detail = f"exit={task_result.returncode} {task_result.stderr.strip()}"
        except Exception as exc:
            scheduled_task_detail = str(exc)
    add(checks, "Hermes Gateway Scheduled Task primary", scheduled_task_ok, scheduled_task_detail)

    config_path = hermes_home / "config.yaml"
    telegram_ok = False
    telegram_detail = f"missing: {config_path}"
    if config_path.is_file():
        try:
            import yaml

            config = yaml.safe_load(read_text(config_path)) or {}
            telegram_enabled = bool((config.get("telegram") or {}).get("enabled"))
            platform_enabled = bool(((config.get("platforms") or {}).get("telegram") or {}).get("enabled"))
            telegram_ok = telegram_enabled and platform_enabled
            telegram_detail = f"telegram.enabled={telegram_enabled} platforms.telegram.enabled={platform_enabled}"
        except Exception as exc:
            telegram_detail = f"config parse failed: {exc}"
    add(checks, "Hermes Telegram delivery enabled", telegram_ok, telegram_detail)

    if hermes_python.is_file():
        runtime_env = os.environ.copy()
        runtime_env["HERMES_HOME"] = str(hermes_home)
        runtime_env.setdefault("PYTHONUTF8", "1")
        site_packages = hermes_agent / "venv" / "Lib" / "site-packages"
        runtime_env["PYTHONPATH"] = os.pathsep.join(
            [str(hermes_agent), str(site_packages), runtime_env.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep)
        for command, label, needle in (
            (
                [str(hermes_python), "-m", "hermes_cli.main", "gateway", "status"],
                "Hermes Gateway running",
                "Gateway process running",
            ),
            (
                [str(hermes_python), "-m", "hermes_cli.main", "cron", "status"],
                "Hermes cron ticker running",
                "Gateway is running",
            ),
        ):
            try:
                result = subprocess.run(
                    command,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=30,
                    env=runtime_env,
                )
                output = (result.stdout or "") + (result.stderr or "")
                ok = result.returncode == 0 and needle in output
                detail = f"exit={result.returncode} matched={needle in output}"
            except Exception as exc:
                ok = False
                detail = str(exc)
            add(checks, label, ok, detail)


def audit_hermes(checks: list[dict[str, Any]], hermes_home: Path, hermes_agent: Path) -> None:
    jobs, error = load_hermes_jobs(hermes_home, hermes_agent)
    add(checks, "Hermes cron API readable", not error, error or f"{len(jobs)} jobs loaded")
    if error:
        return

    by_name: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        by_name.setdefault(str(job.get("name") or ""), []).append(job)

    extras = [
        str(job.get("name") or "")
        for job in jobs
        if re.search(r"(HUAIDJ|Sanji)", str(job.get("name") or ""), re.I)
        and str(job.get("name") or "") not in EXPECTED_HERMES_JOBS
        and str(job.get("name") or "") not in ALLOWED_EXTRA_HERMES_JOBS
        and str(job.get("name") or "") not in LEGACY_ALLOWED_PAUSED_HERMES_JOBS
    ]
    add(checks, "No extra HUAIDJ/Sanji Hermes jobs", not extras, "extras=" + ", ".join(extras))

    for name in sorted(LEGACY_ALLOWED_PAUSED_HERMES_JOBS):
        for job in by_name.get(name, []):
            paused = str(job.get("state")) == "paused" or bool(job.get("enabled", True)) is False
            add(
                checks,
                f"Legacy Hermes job paused: {name}",
                paused,
                f"state={job.get('state')} enabled={job.get('enabled')}",
            )

    for name, expected in EXPECTED_HERMES_JOBS.items():
        expected_deliver = expected.get("deliver", "weixin")
        matches = by_name.get(name, [])
        active_matches = [
            job for job in matches
            if bool(job.get("enabled")) is True and str(job.get("state")) == "scheduled"
        ]
        paused_duplicates = [job for job in matches if job not in active_matches]
        add(
            checks,
            f"Hermes job has one active owner: {name}",
            len(active_matches) == 1,
            f"total={len(matches)} active={len(active_matches)} paused_duplicates={len(paused_duplicates)}",
        )
        add(
            checks,
            f"Hermes duplicate jobs paused: {name}",
            all(str(job.get("state")) == "paused" or bool(job.get("enabled", True)) is False for job in paused_duplicates),
            f"paused_duplicates={len(paused_duplicates)}",
        )
        if not active_matches:
            continue
        job = active_matches[0]
        add(checks, f"Hermes job scheduled: {name}", str(job.get("state")) == "scheduled", f"state={job.get('state')}")
        add(checks, f"Hermes job enabled: {name}", bool(job.get("enabled")) is True, f"enabled={job.get('enabled')}")
        add(checks, f"Hermes job no_agent: {name}", bool(job.get("no_agent")) is True, f"no_agent={job.get('no_agent')}")
        add(
            checks,
            f"Hermes job deliver {expected_deliver}: {name}",
            str(job.get("deliver")) == expected_deliver,
            f"deliver={job.get('deliver')}",
        )
        add(
            checks,
            f"Hermes job wrap_response false: {name}",
            job.get("wrap_response") is False,
            f"wrap_response={job.get('wrap_response')}",
        )
        add(
            checks,
            f"Hermes job schedule: {name}",
            schedule_expr(job) == expected["schedule_expr"],
            f"schedule={schedule_expr(job)} expected={expected['schedule_expr']}",
        )
        add(
            checks,
            f"Hermes job script: {name}",
            str(job.get("script")) == expected["script"],
            f"script={job.get('script')} expected={expected['script']}",
        )
        add(
            checks,
            f"Hermes job workdir: {name}",
            str(job.get("workdir") or "") == str(REPO),
            f"workdir={job.get('workdir')} expected={REPO}",
        )

    scripts_root = hermes_home / "scripts"
    for rel, tokens in EXPECTED_HERMES_SCRIPTS.items():
        path = scripts_root / rel.replace("/", os.sep)
        ok, detail = file_contains(path, list(tokens))
        if ok:
            text = read_text(path)
            forbidden = [
                token for token in FORBIDDEN_HERMES_SCRIPT_TOKENS.get(rel, ()) if token in text
            ]
            if forbidden:
                ok = False
                detail = "forbidden tokens: " + ", ".join(forbidden)
        add(checks, f"Hermes script contract: {rel}", ok, detail)


def audit_windows_tasks(checks: list[dict[str, Any]]) -> None:
    script = r"""
$names = @(
  'HUAIDJ Sanji Daily Publish Evening',
  'HUAIDJ Sanji Daily Publish Noon',
  'HUAIDJ Sanji Desktop Export Evening',
  'HUAIDJ Sanji Desktop Export Noon',
  'HUAIDJ Sanji RSS Fast Watch'
)
$rows = foreach ($name in $names) {
  $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
  if ($null -eq $task) {
    [pscustomobject]@{TaskName=$name; State='Missing'}
  } else {
    [pscustomobject]@{TaskName=$name; State=[string]$task.State}
  }
}
$rows | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            text=True,
            capture_output=True,
            timeout=30,
        )
    except Exception as exc:
        add(checks, "Windows task query", False, str(exc), severity="warn")
        return
    if result.returncode != 0:
        add(checks, "Windows task query", False, result.stderr.strip(), severity="warn")
        return
    try:
        payload = json.loads(result.stdout or "[]")
        rows = payload if isinstance(payload, list) else [payload]
    except Exception as exc:
        add(checks, "Windows task query parse", False, str(exc), severity="warn")
        return
    for row in rows:
        name = str(row.get("TaskName"))
        state = str(row.get("State"))
        ok = state in {"Disabled", "Missing"}
        add(checks, f"Windows task disabled: {name}", ok, f"state={state}")


def audit_codex(checks: list[dict[str, Any]]) -> None:
    if not CODEX_AUTOMATION.exists():
        add(checks, "Codex duplicate executor absent or paused", True, f"absent: {CODEX_AUTOMATION}")
        return
    text = read_text(CODEX_AUTOMATION)
    ok = 'status = "PAUSED"' in text and "Hermes owns execution" in text and "PosterVlMaxImages 0" in text
    add(checks, "Codex duplicate executor absent or paused", ok, "weekly-daily-incremental-18")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", default="", help="Optional path to write full audit JSON.")
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(DEFAULT_HERMES_HOME)))
    parser.add_argument(
        "--hermes-agent",
        "--hermes-runtime",
        dest="hermes_agent",
        default=os.environ.get("HERMES_AGENT_ROOT", str(resolve_hermes_runtime_root())),
        help="Immutable Hermes source/runtime root.",
    )
    args = parser.parse_args()

    hermes_home = Path(args.hermes_home)
    hermes_agent = Path(args.hermes_agent)

    checks: list[dict[str, Any]] = []
    add(checks, "repo root", REPO.exists(), str(REPO))
    add(checks, "Hermes home exists", hermes_home.exists(), str(hermes_home))
    add(checks, "Hermes agent exists", hermes_agent.exists(), str(hermes_agent))

    audit_wrappers(checks)
    audit_docs(checks)
    audit_hermes_runtime(checks, hermes_home, hermes_agent)
    audit_hermes(checks, hermes_home, hermes_agent)
    audit_windows_tasks(checks)
    audit_codex(checks)

    failures = [c for c in checks if c["status"] == "fail"]
    warnings = [c for c in checks if c["status"] == "warn"]
    report = {
        "schema_version": "huaidj_sanji_hermes_contract_audit.v1",
        "ok": not failures,
        "failure_count": len(failures),
        "warning_count": len(warnings),
        "repo": str(REPO),
        "hermes_home": str(hermes_home),
        "hermes_agent": str(hermes_agent),
        "checks": checks,
    }

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
