#!/usr/bin/env python3
"""Install or repair Hermes desktop cron jobs for HUAIDJ Sanji daily publish.

Default mode is dry-run. Pass --apply to write the no-agent Hermes jobs
and their script files. This script stores no secrets and does not start a
publish run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[3]
DEFAULT_HERMES_HOME = Path(r"F:\DevData\Hermes")
DEFAULT_HERMES_AGENT = DEFAULT_HERMES_HOME / "hermes-agent"
DEFAULT_REPORT_ROOT = Path(r"F:\DevData\HuaidjRuntime\state\reports")


def resolve_hermes_runtime_root() -> Path:
    """Resolve the immutable Hermes source/runtime selected for this user."""

    configured = os.environ.get("HERMES_DESKTOP_HERMES_ROOT", "").strip()
    if not configured and os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                configured = str(winreg.QueryValueEx(key, "HERMES_DESKTOP_HERMES_ROOT")[0] or "").strip()
        except (FileNotFoundError, OSError):
            configured = ""
    return Path(configured) if configured else DEFAULT_HERMES_AGENT

SCRIPT_TEMPLATES = {
    "huaidj/sanji_publish_afternoon.py": '''"""HUAIDJ Sanji publish — Wed 21:10 + Fri 20:10 off-peak weekly plan.

The Hermes cron process remains the lifecycle owner until both the Sanji export
and the online package publish finish.  A child failure therefore becomes the
Hermes execution result instead of an untracked detached process.
"""
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


HERMES_HOME = Path(os.environ.get("HERMES_HOME", r"C:\\Users\\pc\\AppData\\Local\\hermes"))
REPO = Path(os.environ.get("HUAIDJ_REPO", r"C:\\code\\githubstar\\wechathtmldownload"))
REPORT_ROOT = Path(os.environ.get("HUAIDJ_REPORT_ROOT", r"F:\\DevData\\HuaidjRuntime\\state\\reports"))
LOG_DIR = REPORT_ROOT / "hermes_scheduled" / "sanji_publish"
os.environ["HUAIDJ_REPORT_ROOT"] = str(REPORT_ROOT)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True
POWERSHELL = shutil.which("pwsh.exe") or "pwsh.exe"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
EXPORT_CMD = [
    POWERSHELL,
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    str(REPO / "tools" / "stage7_rewrite" / "run_sanji_desktop_recent_export.ps1"),
    "-ReportRoot",
    str(REPORT_ROOT),
]
PUBLISH_CMD = [
    POWERSHELL,
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    str(REPO / "tools" / "stage7_rewrite" / "run_huaidj_sanji_daily_twice.ps1"),
    "-Slot",
    "manual",
    "-SkipSanjiExport",
    "-DeployBackend",
    "-MinExpectedItems",
    "40",
    "-PosterExtractionMode",
    "vl_direct_qwen",
    "-PosterVlMaxImages",
    "0",
    "-ReportRoot",
    str(REPORT_ROOT),
]


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    proxy_url = env.get("HUAIDJ_PROXY_URL", "").strip()
    if proxy_url:
        env["HTTP_PROXY"] = proxy_url
        env["HTTPS_PROXY"] = proxy_url
    return env


def _tail(path: Path, limit: int = 4000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = LOG_DIR / f"huaidj-sanji-wedfri-{stamp}.log"
    result_code = 0
    failed_step = ""
    with log_path.open("a", encoding="utf-8", errors="replace") as log_handle:
        for label, command in (("Sanji export", EXPORT_CMD), ("activity publish", PUBLISH_CMD)):
            log_handle.write(f"[{datetime.now().isoformat()}] {label} started\\n")
            log_handle.flush()
            try:
                result = subprocess.run(
                    command,
                    cwd=str(REPO),
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    env=_child_env(),
                    creationflags=CREATE_NO_WINDOW,
                )
                result_code = int(result.returncode)
            except Exception as exc:
                log_handle.write(f"{label} launch failed: {exc}\\n")
                result_code = 2
            log_handle.write(f"[{datetime.now().isoformat()}] {label} exit={result_code}\\n")
            log_handle.flush()
            if result_code != 0:
                failed_step = label
                break
    if result_code != 0:
        print(f"[FAIL] HUAIDJ {failed_step} failed: exit={result_code} log={log_path}")
        tail = _tail(log_path)
        if tail:
            print(tail)
        return result_code
    print(f"[OK] HUAIDJ Sanji export and online activity publish completed. log={log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
''',
    "huaidj/sanji_rss_fast_watch.py": '''import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO = Path(os.environ.get("HUAIDJ_REPO", r"C:\\code\\githubstar\\wechathtmldownload"))
REPORT_ROOT = Path(os.environ.get("HUAIDJ_REPORT_ROOT", r"F:\\DevData\\HuaidjRuntime\\state\\reports"))
os.environ["HUAIDJ_REPORT_ROOT"] = str(REPORT_ROOT)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True
POWERSHELL = shutil.which("pwsh.exe") or "pwsh.exe"
CMD = [
    POWERSHELL,
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    str(REPO / "tools" / "stage7_rewrite" / "run_huaidj_sanji_rss_fast_watch.ps1"),
    "-DetectOnly",
    "-PosterVlModel",
    "qwen3.6-plus",
    "-PosterVlMaxImages",
    "0",
    "-ReportRoot",
    str(REPORT_ROOT),
]


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    proxy_url = env.get("HUAIDJ_PROXY_URL", "").strip()
    if proxy_url:
        env["HTTP_PROXY"] = proxy_url
        env["HTTPS_PROXY"] = proxy_url
    return env


def main() -> int:
    result = subprocess.run(
        CMD,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env=_child_env(),
    )
    if result.returncode == 0:
        return 0
    tail = ((result.stdout or "") + "\\n" + (result.stderr or "")).strip()[-4000:]
    print(f"[FAIL] HUAIDJ Sanji RSS fast watch command failed: exit={result.returncode}")
    if tail:
        print(tail)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
''',
    "huaidj/audit_coverage_gap.py": '''"""HUAIDJ coverage audit for the off-peak Wed 21:10 + Fri 20:10 plan."""
import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path


REPO = Path(os.environ.get("HUAIDJ_REPO", r"C:\\code\\githubstar\\wechathtmldownload"))
REPORT_ROOT = Path(os.environ.get("HUAIDJ_REPORT_ROOT", r"F:\\DevData\\HuaidjRuntime\\state\\reports"))
REPORT_DIR = REPORT_ROOT / "coverage_audit"
SANJI_DB = Path(os.environ.get("USERPROFILE", r"C:\\Users\\pc")) / "AppData" / "Roaming" / "sanji" / "sanji.db"
DEFAULT_RUNTIME_DATA_ROOT = Path(r"F:\\DevData\\HuaidjRuntime\\state\\weekly_activity_cloudrun\\data")
API_DIR = Path(os.environ.get("HUAIDJ_CURRENT_RELEASE_DIR", str(DEFAULT_RUNTIME_DATA_ROOT / "current_release")))
os.environ["HUAIDJ_REPORT_ROOT"] = str(REPORT_ROOT)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

REPORT_DIR.mkdir(parents=True, exist_ok=True)

NOW = datetime.datetime.now()
TODAY = NOW.strftime("%Y-%m-%d")
WEEKDAY = NOW.weekday()

this_monday = (NOW - datetime.timedelta(days=WEEKDAY)).replace(hour=0, minute=0, second=0, microsecond=0)
wed_run = this_monday + datetime.timedelta(days=2, hours=21, minutes=10)
fri_run = this_monday + datetime.timedelta(days=4, hours=20, minutes=10)

if NOW >= fri_run:
    last_run = fri_run
    next_run = this_monday + datetime.timedelta(days=9, hours=21, minutes=10)
elif NOW >= wed_run:
    last_run = wed_run
    next_run = fri_run
else:
    last_run = this_monday - datetime.timedelta(days=3) + datetime.timedelta(hours=20, minutes=10)
    next_run = wed_run


def load_published_articles_since(cutoff_ts):
    try:
        con = sqlite3.connect(f"file:{SANJI_DB}?mode=ro", uri=True)
        row = con.execute(
            "SELECT COUNT(*), MIN(publish_time), MAX(publish_time) "
            "FROM wechat_article WHERE publish_time > ? AND fetch_status = 'ok'",
            (cutoff_ts,),
        ).fetchone()
        con.close()
        return {"count": row[0] or 0, "min_ts": row[1], "max_ts": row[2]}
    except Exception as exc:
        return {"count": 0, "error": str(exc)}


def load_api_events():
    current_path = API_DIR / "current.json"
    if not current_path.exists():
        return []
    data = json.loads(current_path.read_text(encoding="utf-8"))
    events = []
    for item in data.get("items", []):
        event_date = str(item.get("event_date_start", ""))[:10]
        post_date = str(item.get("post_date", ""))[:10]
        if event_date and len(event_date) == 10:
            events.append(
                {
                    "id": item.get("id", ""),
                    "title": str(item.get("title", ""))[:60],
                    "event_date": event_date,
                    "post_date": post_date,
                    "venue": str(item.get("venue", ""))[:30],
                }
            )
    return events


def classify_events(events):
    stats = {
        "total": len(events),
        "captured_on_time": 0,
        "captured_late": 0,
        "announced_after_event": 0,
        "no_post_date": 0,
        "late_details": [],
    }
    for event in events:
        try:
            event_dt = datetime.datetime.strptime(event["event_date"], "%Y-%m-%d")
        except ValueError:
            continue
        post_dt = None
        if event["post_date"] and len(event["post_date"]) == 10:
            try:
                post_dt = datetime.datetime.strptime(event["post_date"], "%Y-%m-%d")
            except ValueError:
                pass
        if not post_dt:
            stats["no_post_date"] += 1
            post_dt = event_dt - datetime.timedelta(days=3)

        captured = False
        if post_dt <= wed_run and event_dt > wed_run:
            captured = True
        if not captured and post_dt <= fri_run and event_dt > fri_run:
            captured = True
        if not captured and post_dt <= fri_run and wed_run <= event_dt <= fri_run:
            captured = True

        if captured and (event_dt - post_dt).days >= 0:
            stats["captured_on_time"] += 1
        elif captured:
            stats["announced_after_event"] += 1
        else:
            stats["captured_late"] += 1
            stats["late_details"].append(
                {
                    "id": event["id"],
                    "title": event["title"],
                    "event_date": event["event_date"],
                    "post_date": event["post_date"] or "unknown",
                    "gap_days": (event_dt - post_dt).days,
                    "venue": event["venue"],
                }
            )
    return stats


def build_report(stats, article_stats):
    total = stats["total"]
    on_time_pct = stats["captured_on_time"] / total * 100 if total else 0
    late_pct = stats["captured_late"] / total * 100 if total else 0
    lines = [
        f"# HUAIDJ Coverage Audit — {TODAY}",
        "",
        f"**Pipeline**: Wed 21:10 + Fri 20:10 | **Last run**: {last_run:%Y-%m-%d %H:%M} | **Next**: {next_run:%Y-%m-%d %H:%M}",
        "",
        "## Coverage",
        "| Metric | Count | % |",
        "|--------|-------|---|",
        f"| Total events | {total} | 100% |",
        f"| On time (captured before event) | {stats['captured_on_time']} | {on_time_pct:.0f}% |",
        f"| Late (captured after event) | {stats['captured_late']} | {late_pct:.0f}% |",
        f"| No post_date | {stats['no_post_date']} | - |",
        "",
        "## Article Feed",
        f"- New articles since last run: {article_stats.get('count', 0)}",
    ]
    if article_stats.get("min_ts"):
        lines.append(f"- Earliest: {datetime.datetime.fromtimestamp(article_stats['min_ts']):%Y-%m-%d %H:%M}")
    if stats["late_details"]:
        lines.extend(["", "## Late Events", "| Event Date | Post Date | Gap | Title | Venue |", "|---|---|---|---|---|"])
        for row in stats["late_details"][:20]:
            lines.append(
                f"| {row['event_date']} | {row['post_date']} | {row['gap_days']}d | {row['title'][:40]} | {row['venue']} |"
            )
    lines.extend(["", "---", f"*Generated {NOW.isoformat()}*"])
    return "\\n".join(lines)


def main():
    article_stats = load_published_articles_since(int(last_run.timestamp()))
    events = load_api_events()
    stats = classify_events(events)
    report = build_report(stats, article_stats)

    json_path = REPORT_DIR / f"coverage_{TODAY}.json"
    json_path.write_text(
        json.dumps(
            {
                "date": TODAY,
                "pipeline": "Wed 21:10 + Fri 20:10",
                "last_run": last_run.isoformat(),
                "next_run": next_run.isoformat(),
                "article_stats": article_stats,
                "stats": {k: v for k, v in stats.items() if k != "late_details"},
                "late_count": len(stats["late_details"]),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (REPORT_DIR / f"coverage_{TODAY}.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"\\nLog: {json_path}")


if __name__ == "__main__":
    sys.exit(main())
''',
    "huaidj/sanji_login_reminder.py": '''"""Reminder to renew Sanji official-account login authorization.

This script only prints a message for Hermes delivery. It does not read Sanji
databases, cookies, tokens, browser credentials, or WeChat profile data.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


REPORT_ROOT = Path(os.environ.get("HUAIDJ_REPORT_ROOT", r"F:\\DevData\\HuaidjRuntime\\state\\reports"))
os.environ["HUAIDJ_REPORT_ROOT"] = str(REPORT_ROOT)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True


MESSAGE = """Sanji 公众号登录授权提醒

Sanji / 公号三刀的公众号登录授权通常只有 2 天。
请打开 Sanji，确认公众号登录状态，并重新登录或续期授权。

安全边界：不要把 cookie、token、验证码或授权链接发给任何人。
登录完成后，下一次 Hermes RSS Fast Watch 会继续使用 Sanji 本地缓存刷新。"""


def main() -> int:
    print(MESSAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
    "huaidj/atlas_v2_sanji_import_nightly.py": '''"""HUAIDJ AtlasV2 nightly full-candidate import.

This job waits for the complete candidate build and returns its terminal status
to Hermes.  It advances the checkpoint only through the orchestrator's
``--advance-checkpoint`` success gate and never promotes production or restarts
a public service.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


HERMES_HOME = Path(os.environ.get("HERMES_HOME", r"C:\\Users\\pc\\AppData\\Local\\hermes"))
REPO = Path(os.environ.get("HUAIDJ_REPO", r"C:\\code\\githubstar\\wechathtmldownload"))
PYTHON_EXE = Path(os.environ.get("HUAIDJ_PYTHON") or sys.executable)
SANJI_ROOT = Path(os.environ.get("SANJI_ROOT", str(Path(os.environ.get("APPDATA", "")) / "sanji")))
SANJI_ARTICLES_ROOT = Path(os.environ.get("SANJI_HOT_ARTICLES_ROOT", r"E:\\sanji_hot\\articles"))
REPORT_ROOT = Path(os.environ.get("HUAIDJ_REPORT_ROOT", r"F:\\DevData\\HuaidjRuntime\\state\\reports"))
LOG_DIR = REPORT_ROOT / "atlas_v2_import"
LOCK_PATH = REPORT_ROOT / "_locks" / "atlas_v2_import.lock"
os.environ["HUAIDJ_REPORT_ROOT"] = str(REPORT_ROOT)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True
RUN_ID = os.environ.get("ATLAS_RUN_ID", "").strip()
RUN_LIMIT = 0
MAX_COST_RMB = 15.0
VISION_WORKERS = 4
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CRITICAL_ENV_KEYS = (
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "MIMO_API_KEY",
    "MIMO_VISION_API_KEY",
    "ATLAS_HISTORICAL_VENUE_GEO",
    "HUAIDJ_PROXY_URL",
)


def _fresh_launch_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["HUAIDJ_REPORT_ROOT"] = str(REPORT_ROOT)
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                for name in CRITICAL_ENV_KEYS:
                    try:
                        value, _ = winreg.QueryValueEx(key, name)
                    except FileNotFoundError:
                        continue
                    if value:
                        env[name] = str(value)
        except OSError:
            pass
    proxy_url = env.get("HUAIDJ_PROXY_URL", "").strip()
    if proxy_url:
        env["HTTP_PROXY"] = proxy_url
        env["HTTPS_PROXY"] = proxy_url
    return env


def _lock_handle(handle) -> bool:
    """Acquire one kernel-enforced byte lock and keep ``handle`` open."""
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b" ")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        return False
    return True


def _unlock_handle(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _acquire_lock(log_path: Path):
    """Return an owned lock handle, or ``None`` when another run owns it.

    The sentinel intentionally remains after a run.  Ownership comes from the
    kernel lock, not a check-then-write PID file, so process crashes release it
    automatically and concurrent starts cannot both pass the gate.
    """
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("a+b")
    if not _lock_handle(handle):
        handle.close()
        return None
    payload = json.dumps(
        {
            "schema_version": "atlas_v2_import_lock.v4",
            "started_at": datetime.now().isoformat(),
            "pid": os.getpid(),
            "log": str(log_path),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    handle.seek(0)
    handle.truncate()
    handle.write(payload)
    handle.flush()
    os.fsync(handle.fileno())
    return handle


def _release_lock(handle) -> None:
    try:
        _unlock_handle(handle)
    finally:
        handle.close()


def _tail(path: Path, limit: int = 4000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


def main() -> int:
    orchestrator = REPO / "tools" / "atlas_rebuild" / "run_atlas_v2_sanji_import.py"
    if not orchestrator.is_file():
        print(f"[BLOCKED] AtlasV2 orchestrator missing: {orchestrator}")
        return 2
    if not PYTHON_EXE.is_file():
        print(f"[BLOCKED] HUAIDJ Python missing: {PYTHON_EXE}")
        return 2
    try:
        dependency = subprocess.run(
            [str(PYTHON_EXE), "-c", "import rapidocr_onnxruntime"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=30,
            env=_fresh_launch_env(),
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        print("[BLOCKED] rapidocr_onnxruntime dependency probe timed out.")
        return 124
    except Exception as exc:
        print(f"[BLOCKED] HUAIDJ Python dependency probe failed: {exc}")
        return 2
    if dependency.returncode != 0:
        print("[BLOCKED] rapidocr_onnxruntime is unavailable in HUAIDJ_PYTHON.")
        return int(dependency.returncode) or 2
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = LOG_DIR / f"atlas-v2-import-nightly-{stamp}.log"
    lock_handle = _acquire_lock(log_path)
    if lock_handle is None:
        print(f"[DEFERRED] AtlasV2 import already running: {LOCK_PATH}")
        return 75
    command = [
        str(PYTHON_EXE),
        str(orchestrator),
        "--sanji-root",
        str(SANJI_ROOT),
        "--articles-root",
        str(SANJI_ARTICLES_ROOT),
        "--limit",
        str(RUN_LIMIT),
        "--max-cost-rmb",
        str(MAX_COST_RMB),
        "--vision-workers",
        str(VISION_WORKERS),
        "--advance-checkpoint",
    ]
    if RUN_ID:
        command.extend(["--run-id", RUN_ID])
    try:
        with log_path.open("a", encoding="utf-8", errors="replace") as log_handle:
            result = subprocess.run(
                command,
                cwd=str(REPO),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                env=_fresh_launch_env(),
                creationflags=CREATE_NO_WINDOW,
            )
        result_code = int(result.returncode)
    except Exception as exc:
        print(f"[FAIL] AtlasV2 import launch failed: {exc} log={log_path}")
        return 2
    finally:
        _release_lock(lock_handle)
    if result_code != 0:
        print(f"[FAIL] AtlasV2 candidate import failed: exit={result_code} log={log_path}")
        tail = _tail(log_path)
        if tail:
            print(tail)
        return result_code
    print(
        f"[OK] AtlasV2 candidate import completed. log={log_path}. "
        "No production promotion or service restart was performed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
    "huaidj/health_check.py": '''"""HUAIDJ CloudRun API and data-freshness health bridge."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


HERMES_HOME = Path(os.environ.get("HERMES_HOME", r"C:\\Users\\pc\\AppData\\Local\\hermes"))
REPO = Path(os.environ.get("HUAIDJ_REPO", r"C:\\code\\githubstar\\wechathtmldownload"))
PYTHON_EXE = os.environ.get("HUAIDJ_PYTHON") or sys.executable
REPORT_ROOT = Path(os.environ.get("HUAIDJ_REPORT_ROOT", r"F:\\DevData\\HuaidjRuntime\\state\\reports"))
os.environ["HUAIDJ_REPORT_ROOT"] = str(REPORT_ROOT)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True
CMD = [
    PYTHON_EXE,
    str(REPO / "tools" / "stage7_rewrite" / "scripts" / "report_huaidj_package_api_tg_status.py"),
    "--state-file",
    str(HERMES_HOME / "scripts" / "huaidj" / ".health_state.json"),
    "--json-out",
    str(REPORT_ROOT / "huaidj_health" / "latest.json"),
    "--force",
]


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    proxy_url = env.get("HUAIDJ_PROXY_URL", "").strip()
    if proxy_url:
        env["HTTP_PROXY"] = proxy_url
        env["HTTPS_PROXY"] = proxy_url
    return env


def _emit(text: str) -> None:
    """Write child output without crashing on a legacy Windows console codec."""
    if not text or sys.stdout is None:
        return
    encoding = getattr(sys.stdout, "encoding", None)
    rendered = text
    if encoding:
        rendered = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    sys.stdout.write(rendered)
    sys.stdout.flush()


def main() -> int:
    try:
        result = subprocess.run(
            CMD + sys.argv[1:],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=90,
            env=_child_env(),
        )
    except subprocess.TimeoutExpired as exc:
        _emit(f"HUAIDJ CloudRun API / Data freshness health timed out: {exc}\\n")
        return 124
    except Exception as exc:
        _emit(f"HUAIDJ CloudRun API / Data freshness health launch failed: {exc}\\n")
        return 2
    if result.stdout:
        _emit(result.stdout)
    if result.returncode != 0:
        tail = ((result.stdout or "") + "\\n" + (result.stderr or "")).strip()[-3500:]
        _emit(f"HUAIDJ health check failed: exit={result.returncode}\\n")
        if tail:
            _emit(tail + "\\n")
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
''',
    "huaidj/package_api_tg_status.py": '''"""Telegram bridge for HUAIDJ activity package and API status.

Hermes runs this as a no-agent cron script with deliver=telegram. The repository
script performs public API checks and local JSON cross-validation, then prints
only when there is a package/status change, degradation, or recovery.
"""

from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path


HERMES_HOME = Path(os.environ.get("HERMES_HOME", r"C:\\Users\\pc\\AppData\\Local\\hermes"))
REPO = Path(os.environ.get("HUAIDJ_REPO", r"C:\\code\\githubstar\\wechathtmldownload"))
PYTHON_EXE = os.environ.get("HUAIDJ_PYTHON") or sys.executable
REPORT_ROOT = Path(os.environ.get("HUAIDJ_REPORT_ROOT", r"F:\\DevData\\HuaidjRuntime\\state\\reports"))
os.environ["HUAIDJ_REPORT_ROOT"] = str(REPORT_ROOT)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True
CMD = [
    PYTHON_EXE,
    str(REPO / "tools" / "stage7_rewrite" / "scripts" / "report_huaidj_package_api_tg_status.py"),
    "--state-file",
    str(HERMES_HOME / "scripts" / "huaidj" / ".package_api_tg_state.json"),
    "--json-out",
    str(REPORT_ROOT / "huaidj_package_api_tg_status" / "latest.json"),
]


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    proxy_url = env.get("HUAIDJ_PROXY_URL", "").strip()
    if proxy_url:
        env["HTTP_PROXY"] = proxy_url
        env["HTTPS_PROXY"] = proxy_url
    return env


def _emit(text: str) -> None:
    """Write child output without crashing on a legacy Windows console codec."""
    if not text or sys.stdout is None:
        return
    encoding = getattr(sys.stdout, "encoding", None)
    rendered = text
    if encoding:
        rendered = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    sys.stdout.write(rendered)
    sys.stdout.flush()


def main() -> int:
    try:
        result = subprocess.run(
            CMD + sys.argv[1:],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=90,
            env=_child_env(),
        )
    except subprocess.TimeoutExpired as exc:
        _emit(f"HUAIDJ 活动包/API TG 状态脚本超时: {exc}\\n")
        return 124
    except Exception as exc:
        _emit(f"HUAIDJ 活动包/API TG 状态脚本启动失败: {exc}\\n")
        return 2
    if result.stdout:
        _emit(result.stdout)
    if result.returncode != 0:
        tail = ((result.stdout or "") + "\\n" + (result.stderr or "")).strip()[-3500:]
        _emit(f"HUAIDJ 活动包/API TG 状态脚本执行失败: exit={result.returncode}\\n")
        if tail:
            _emit(tail + "\\n")
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
''',
}

SCRIPT_CONTRACT_TOKENS = {
    "huaidj/sanji_publish_afternoon.py": (
        "run_sanji_desktop_recent_export.ps1",
        "run_huaidj_sanji_daily_twice.ps1",
        "-Slot",
        "manual",
        "-SkipSanjiExport",
        "PosterVlMaxImages",
        "vl_direct_qwen",
        '"0"',
        "HUAIDJ_REPO",
        "HUAIDJ_REPORT_ROOT",
        "PYTHONDONTWRITEBYTECODE",
        "HUAIDJ_PROXY_URL",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "-ReportRoot",
        "CREATE_NO_WINDOW",
        "subprocess.run(",
        "return result_code",
        "online activity publish completed",
    ),
    "huaidj/sanji_rss_fast_watch.py": (
        "run_huaidj_sanji_rss_fast_watch.ps1",
        "-DetectOnly",
        "HUAIDJ_REPO",
        "HUAIDJ_REPORT_ROOT",
        "PYTHONDONTWRITEBYTECODE",
        "HUAIDJ_PROXY_URL",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "-ReportRoot",
        "return result.returncode",
    ),
    "huaidj/audit_coverage_gap.py": (
        "Wed 21:10 + Fri 20:10",
        "hours=20, minutes=10",
        "HUAIDJ_REPORT_ROOT",
        "PYTHONDONTWRITEBYTECODE",
    ),
    "huaidj/sanji_login_reminder.py": (
        "公众号登录授权提醒",
        "2 天",
        "cookie",
        "token",
        "HUAIDJ_REPORT_ROOT",
        "PYTHONDONTWRITEBYTECODE",
    ),
    "huaidj/package_api_tg_status.py": (
        "report_huaidj_package_api_tg_status.py",
        ".package_api_tg_state.json",
        "huaidj_package_api_tg_status",
        "HUAIDJ_PYTHON",
        "HUAIDJ_REPORT_ROOT",
        "PYTHONDONTWRITEBYTECODE",
        "HUAIDJ_PROXY_URL",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "def _emit(text: str) -> None:",
        'text.encode(encoding, errors="replace").decode(encoding, errors="replace")',
        "sys.stdout.write(rendered)",
        "return int(result.returncode)",
    ),
    "huaidj/health_check.py": (
        "CloudRun API",
        "data-freshness",
        "report_huaidj_package_api_tg_status.py",
        "HUAIDJ_PYTHON",
        "HUAIDJ_REPORT_ROOT",
        "PYTHONDONTWRITEBYTECODE",
        "HUAIDJ_PROXY_URL",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "def _emit(text: str) -> None:",
        'text.encode(encoding, errors="replace").decode(encoding, errors="replace")',
        "sys.stdout.write(rendered)",
        "return int(result.returncode)",
    ),
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
        "HUAIDJ_REPORT_ROOT",
        "PYTHONDONTWRITEBYTECODE",
        "ATLAS_HISTORICAL_VENUE_GEO",
        "HUAIDJ_PROXY_URL",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "CREATE_NO_WINDOW",
        "subprocess.run(",
        "msvcrt.locking(",
        "atlas_v2_import_lock.v4",
        "return result_code",
        "No production promotion or service restart",
    ),
}

SCRIPT_FORBIDDEN_TOKENS = {
    "huaidj/sanji_publish_afternoon.py": ("subprocess.Popen(", "[LAUNCHED]", "detached runner"),
    "huaidj/atlas_v2_sanji_import_nightly.py": ("subprocess.Popen(", "[LAUNCHED]", "Runs detached"),
    "huaidj/package_api_tg_status.py": ('"py",', '"-3",'),
}

JOBS = {
    "HUAIDJ Atlas v2 Sanji Import Nightly": {
        "schedule": "40 23 * * *",
        "script": "huaidj/atlas_v2_sanji_import_nightly.py",
        "deliver": "telegram",
    },
    "HUAIDJ Sanji Wed 21:10": {
        "schedule": "10 21 * * 3",
        "script": "huaidj/sanji_publish_afternoon.py",
        "deliver": "telegram",
    },
    "HUAIDJ Sanji Fri 20:10": {
        "schedule": "10 20 * * 5",
        "script": "huaidj/sanji_publish_afternoon.py",
        "deliver": "telegram",
    },
    "HUAIDJ Sanji RSS Fast Watch": {
        "schedule": "*/30 8-23 * * *",
        "script": "huaidj/sanji_rss_fast_watch.py",
        "deliver": "telegram",
    },
    "HUAIDJ Sanji 登录授权提醒": {
        "schedule": "every 2880m",
        "script": "huaidj/sanji_login_reminder.py",
        "deliver": "telegram",
    },
    "HUAIDJ Coverage Audit Wed 22:40": {
        "schedule": "40 22 * * 3",
        "script": "huaidj/audit_coverage_gap.py",
        "deliver": "telegram",
    },
    "HUAIDJ Coverage Audit Fri 21:40": {
        "schedule": "40 21 * * 5",
        "script": "huaidj/audit_coverage_gap.py",
        "deliver": "telegram",
    },
    "HUAIDJ 全栈健康检查": {
        "schedule": "every 60m",
        "script": "huaidj/health_check.py",
        "deliver": "telegram",
    },
    "HUAIDJ 活动包/API TG Monitor": {
        "schedule": "every 30m",
        "script": "huaidj/package_api_tg_status.py",
        "deliver": "telegram",
    },
}

LEGACY_JOB_NAMES = {
    "HUAIDJ Sanji Publish Noon",
    "HUAIDJ Sanji Publish Evening",
    "HUAIDJ Sanji Fri 16:10",
    "HUAIDJ Coverage Audit Fri 17:40",
    "HUAIDJ Sanji Wed+Fri 14:30",
    "HUAIDJ Coverage Audit (post-pipeline)",
}


def load_api(hermes_home: Path, hermes_agent: Path):
    sys.path.insert(0, str(hermes_agent))
    os.environ.setdefault("HERMES_HOME", str(hermes_home))
    from cron.jobs import create_job, load_jobs, update_job  # type: ignore

    return create_job, load_jobs, update_job


def write_scripts(hermes_home: Path, apply: bool) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    scripts_root = hermes_home / "scripts"
    for rel, content in SCRIPT_TEMPLATES.items():
        path = scripts_root / rel.replace("/", os.sep)
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        rendered = content.replace(r"C:\code\githubstar\wechathtmldownload", str(REPO))
        rendered = rendered.replace(r"C:\Users\pc\AppData\Local\hermes", str(hermes_home))
        migrated = old.replace(r"C:\code\githubstar\wechathtmldownload", str(REPO))
        migrated = migrated.replace(r"C:\Users\pc\AppData\Local\hermes", str(hermes_home))
        tokens = SCRIPT_CONTRACT_TOKENS.get(rel, ())
        forbidden = SCRIPT_FORBIDDEN_TOKENS.get(rel, ())
        contract_ok = (
            bool(migrated)
            and all(token in migrated for token in tokens)
            and not any(token in migrated for token in forbidden)
        )
        desired = migrated if contract_ok else rendered
        changed = old != desired
        actions.append({"type": "script", "path": str(path), "contract_ok": contract_ok, "changed": changed})
        if apply and changed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(desired, encoding="utf-8", newline="\n")
    return actions


def ensure_jobs(hermes_home: Path, hermes_agent: Path, apply: bool) -> list[dict[str, Any]]:
    create_job, load_jobs, update_job = load_api(hermes_home, hermes_agent)
    actions: list[dict[str, Any]] = []
    jobs = load_jobs()
    by_name: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        by_name.setdefault(str(job.get("name") or ""), []).append(job)

    for name, spec in JOBS.items():
        expected_deliver = spec.get("deliver", "weixin")
        matches = by_name.get(name, [])
        action: dict[str, Any] = {
            "type": "job",
            "name": name,
            "existing_count": len(matches),
            "schedule": spec["schedule"],
            "script": spec["script"],
            "deliver": expected_deliver,
        }
        if not matches:
            action["action"] = "create"
            if apply:
                job = create_job(
                    prompt=None,
                    schedule=spec["schedule"],
                    name=name,
                    deliver=expected_deliver,
                    script=spec["script"],
                    no_agent=True,
                )
                updated = update_job(
                    job["id"],
                    {
                        "deliver": expected_deliver,
                        "script": spec["script"],
                        "no_agent": True,
                        "wrap_response": False,
                        "state": "scheduled",
                        "enabled": True,
                        "workdir": str(REPO),
                        "paused_reason": None,
                    },
                )
                action["job_id"] = (updated or job).get("id")
        else:
            ordered_matches = sorted(
                matches,
                key=lambda row: (
                    not bool(row.get("enabled")),
                    str(row.get("created_at") or ""),
                    str(row.get("id") or ""),
                ),
            )
            job = ordered_matches[0]
            duplicates = ordered_matches[1:]
            action["action"] = "update"
            action["job_id"] = job.get("id")
            action["duplicate_job_ids"] = [row.get("id") for row in duplicates]
            if apply:
                schedule = job.get("schedule")
                current_expr = ""
                if isinstance(schedule, dict):
                    current_expr = str(schedule.get("expr") or schedule.get("display") or "")
                else:
                    current_expr = str(schedule or "")
                updates = {
                    "deliver": expected_deliver,
                    "script": spec["script"],
                    "no_agent": True,
                    "wrap_response": False,
                    "state": "scheduled",
                    "enabled": True,
                    "workdir": str(REPO),
                    "paused_reason": None,
                }
                if current_expr != spec["schedule"]:
                    updates["schedule"] = spec["schedule"]
                updated = update_job(
                    job["id"],
                    updates,
                )
                action["updated"] = bool(updated)
                paused_duplicates: list[str] = []
                for duplicate in duplicates:
                    duplicate_id = str(duplicate.get("id") or "")
                    if not duplicate_id:
                        continue
                    duplicate_updated = update_job(
                        duplicate_id,
                        {
                            "state": "paused",
                            "enabled": False,
                            "paused_reason": f"Duplicate of canonical Hermes job {job.get('id')}",
                        },
                    )
                    if duplicate_updated:
                        paused_duplicates.append(duplicate_id)
                action["paused_duplicate_job_ids"] = paused_duplicates
        actions.append(action)
    for name in sorted(LEGACY_JOB_NAMES):
        for job in by_name.get(name, []):
            action = {
                "type": "legacy_job",
                "name": name,
                "job_id": job.get("id"),
                "action": "pause",
            }
            if apply:
                updated = update_job(
                    job["id"],
                    {
                        "state": "paused",
                        "enabled": False,
                        "paused_reason": "Superseded by HUAIDJ Sanji Wed 21:10 / Fri 20:10 off-peak weekly schedule",
                    },
                )
                action["updated"] = bool(updated)
            actions.append(action)
    return actions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually write Hermes scripts and jobs.")
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(DEFAULT_HERMES_HOME)))
    parser.add_argument(
        "--hermes-agent",
        "--hermes-runtime",
        dest="hermes_agent",
        default=os.environ.get("HERMES_AGENT_ROOT", str(resolve_hermes_runtime_root())),
        help="Immutable Hermes source/runtime root used to access the cron API.",
    )
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    hermes_home = Path(args.hermes_home)
    hermes_agent = Path(args.hermes_agent)
    report: dict[str, Any] = {
        "schema_version": "huaidj_sanji_hermes_job_installer.v1",
        "applied": bool(args.apply),
        "repo": str(REPO),
        "hermes_home": str(hermes_home),
        "hermes_agent": str(hermes_agent),
        "hermes_runtime": str(hermes_agent),
        "actions": [],
    }
    try:
        report["actions"].extend(write_scripts(hermes_home, args.apply))
        report["actions"].extend(ensure_jobs(hermes_home, hermes_agent, args.apply))
        report["ok"] = True
    except Exception as exc:
        report["ok"] = False
        report["error"] = str(exc)

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
