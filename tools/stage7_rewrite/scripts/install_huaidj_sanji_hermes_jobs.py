#!/usr/bin/env python3
"""Install or repair Hermes desktop cron jobs for HUAIDJ Sanji daily publish.

Default mode is dry-run. Pass --apply to write the no-agent Hermes jobs
and their script files. This script stores no secrets and does not start a
publish run.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import importlib
import json
import os
import shutil
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator


REPO = Path(__file__).resolve().parents[3]
DEFAULT_HERMES_HOME = Path(r"F:\DevData\Hermes")
DEFAULT_HERMES_AGENT = DEFAULT_HERMES_HOME / "hermes-agent"
DEFAULT_REPORT_ROOT = Path(r"F:\DevData\HuaidjRuntime\state\reports")
DEFAULT_BACKUP_ROOT = DEFAULT_REPORT_ROOT / "hermes_job_installer_backups"


def _normalized_path(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path.expanduser().resolve(strict=False))))


def _same_path(left: Path, right: Path) -> bool:
    return _normalized_path(left) == _normalized_path(right)


@contextlib.contextmanager
def _forced_hermes_home(hermes_home: Path) -> Iterator[Path]:
    """Bind one Hermes call to an explicit home and restore its caller env."""

    requested = hermes_home.expanduser().resolve(strict=False)
    previous = os.environ.get("HERMES_HOME")
    had_previous = "HERMES_HOME" in os.environ
    os.environ["HERMES_HOME"] = str(requested)
    try:
        yield requested
    finally:
        if had_previous:
            os.environ["HERMES_HOME"] = previous or ""
        else:
            os.environ.pop("HERMES_HOME", None)


class HermesCronApi:
    """Fail-closed adapter around the Hermes cron store.

    Every operation re-binds ``HERMES_HOME`` and ``use_cron_store`` so an old
    Desktop/terminal environment cannot silently redirect this installer to a
    different profile.  ``reconcile`` owns one locked load/plan/save cycle and
    writes jobs.json at most once.
    """

    def __init__(self, hermes_home: Path, hermes_agent: Path):
        self.hermes_home = hermes_home.expanduser().resolve(strict=False)
        self.hermes_agent = hermes_agent.expanduser().resolve(strict=False)
        self.jobs_file = self.hermes_home / "cron" / "jobs.json"
        self._transaction_lock_depth = 0
        inserted = str(self.hermes_agent)
        sys.path.insert(0, inserted)
        try:
            with _forced_hermes_home(self.hermes_home):
                self.module = importlib.import_module("cron.jobs")
        finally:
            if sys.path and sys.path[0] == inserted:
                sys.path.pop(0)

        module_file = Path(str(getattr(self.module, "__file__", ""))).resolve(strict=False)
        try:
            module_file.relative_to(self.hermes_agent)
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"Hermes cron API came from the wrong runtime: {module_file}; "
                f"expected under {self.hermes_agent}"
            ) from exc
        with self.bound_store():
            pass

    def __iter__(self):
        # Compatibility for older callers/tests that unpacked load_api().
        yield self.create_job
        yield self.load_jobs
        yield self.update_job

    def _assert_store(self) -> None:
        current_store = getattr(self.module, "_current_cron_store", None)
        if not callable(current_store):
            raise RuntimeError("Hermes cron API does not expose _current_cron_store; refusing an unverified store")
        store = current_store()
        actual = Path(str(getattr(store, "jobs_file", "")))
        if not _same_path(actual, self.jobs_file):
            raise RuntimeError(
                f"Hermes cron store mismatch: actual={actual.resolve(strict=False)} "
                f"expected={self.jobs_file.resolve(strict=False)}"
            )

    @contextlib.contextmanager
    def bound_store(self) -> Iterator[None]:
        use_cron_store = getattr(self.module, "use_cron_store", None)
        if not callable(use_cron_store):
            raise RuntimeError("Hermes cron API does not support use_cron_store; refusing implicit storage")
        with _forced_hermes_home(self.hermes_home):
            with use_cron_store(self.hermes_home):
                self._assert_store()
                yield

    def create_job(self, **kwargs):
        with self.bound_store():
            return self.module.create_job(**kwargs)

    def load_jobs(self):
        with self.bound_store():
            return self.module.load_jobs()

    def update_job(self, job_id: str, changes: dict[str, Any]):
        with self.bound_store():
            return self.module.update_job(job_id, changes)

    @contextlib.contextmanager
    def transaction_lock(self) -> Iterator[None]:
        """Hold Hermes' own jobs lock across snapshot, scripts, jobs, and rollback."""

        if self._transaction_lock_depth:
            self._transaction_lock_depth += 1
            try:
                yield
            finally:
                self._transaction_lock_depth -= 1
            return

        with self.bound_store():
            jobs_lock = getattr(self.module, "_jobs_lock", None)
            if not callable(jobs_lock):
                raise RuntimeError("Hermes cron API lacks the cross-process jobs transaction lock")
            with jobs_lock():
                self._assert_store()
                self._transaction_lock_depth = 1
                try:
                    yield
                finally:
                    self._transaction_lock_depth = 0

    def reconcile(
        self,
        planner: Callable[[list[dict[str, Any]], Any], tuple[list[dict[str, Any]], list[dict[str, Any]], bool]],
        *,
        apply: bool,
        already_locked: bool = False,
    ) -> list[dict[str, Any]]:
        def plan_and_maybe_save() -> list[dict[str, Any]]:
            desired, actions, changed = planner(
                copy.deepcopy(list(self.module.load_jobs())), self.module
            )
            self._assert_store()
            if apply and changed:
                save_unlocked(desired)
            return actions

        save_unlocked = getattr(self.module, "_save_jobs_unlocked", None)
        if apply and not callable(save_unlocked):
            raise RuntimeError("Hermes cron API lacks the locked single-write transaction primitives")
        if already_locked:
            if self._transaction_lock_depth <= 0:
                raise RuntimeError("Hermes reconcile already_locked requires the installer transaction lock")
            return plan_and_maybe_save()

        with self.bound_store():
            if not apply:
                return plan_and_maybe_save()
            jobs_lock = getattr(self.module, "_jobs_lock", None)
            if not callable(jobs_lock):
                raise RuntimeError("Hermes cron API lacks the locked single-write transaction primitives")
            with jobs_lock():
                return plan_and_maybe_save()


def _atomic_write_text(path: Path, text: str) -> None:
    """Write one launcher/report beside its target, fsync, then replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class InstallerTransactionError(RuntimeError):
    """An apply write failed after its rollback snapshot was created."""

    def __init__(self, cause: BaseException, *, backup: dict[str, Any], rollback: dict[str, Any]):
        self.cause = cause
        self.backup = backup
        self.rollback = rollback
        super().__init__(
            f"Hermes installation transaction failed; "
            f"baseline_restored={rollback.get('baseline_restored')}: "
            f"{type(cause).__name__}: {cause}"
        )

RUNTIME_SSOT_MARKER = "# __HUAIDJ_RUNTIME_SSOT__"
RUNTIME_SSOT_BLOCK = r'''
HUAIDJ_LAUNCHER_SCHEMA = "huaidj_launcher_runtime_ssot.v1"
INSTALLER_REPO = Path(r"__HUAIDJ_INSTALLER_REPO__")
INSTALLER_PYTHON = Path(r"__HUAIDJ_INSTALLER_PYTHON__")
INSTALLER_REPORT_ROOT = Path(r"__HUAIDJ_INSTALLER_REPORT_ROOT__")
RUNTIME_INPUT_NAMES = ("HUAIDJ_REPO", "HUAIDJ_PYTHON", "HUAIDJ_REPORT_ROOT")


def _same_path(left: Path, right: Path) -> bool:
    try:
        left_value = os.path.normcase(os.path.normpath(str(left.resolve(strict=False))))
        right_value = os.path.normcase(os.path.normpath(str(right.resolve(strict=False))))
    except OSError:
        return False
    return left_value == right_value


def _valid_huaidj_repo(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "tools" / "stage7_rewrite" / "scripts" / "install_huaidj_sanji_hermes_jobs.py").is_file()
    )


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except (OSError, ValueError):
        return False
    return True


def _read_user_runtime_inputs() -> dict[str, str]:
    values: dict[str, str] = {}
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                for name in RUNTIME_INPUT_NAMES:
                    try:
                        value, _ = winreg.QueryValueEx(key, name)
                    except FileNotFoundError:
                        continue
                    if str(value or "").strip():
                        values[name] = str(value).strip()
        except OSError:
            pass
    else:
        for name in RUNTIME_INPUT_NAMES:
            value = os.environ.get(name, "").strip()
            if value:
                values[name] = value
    return values


def _resolve_runtime_settings(*, require_repo: bool = True, require_python: bool = False) -> dict[str, object]:
    """Resolve one coherent non-secret runtime tuple on every launcher start.

    The Gateway process environment may predate an installer repair, so it is
    deliberately not an authority.  HKCU is accepted only when its repo agrees
    exactly with this rendered launcher.  Otherwise the validated Hermes job
    workdir or the installer-rendered defaults win as one atomic tuple.
    """

    installer_repo = INSTALLER_REPO.resolve(strict=False)
    workdir = Path.cwd().resolve(strict=False)
    user_values = _read_user_runtime_inputs()
    user_repo_raw = user_values.get("HUAIDJ_REPO", "")
    user_repo = Path(user_repo_raw).resolve(strict=False) if user_repo_raw else Path()
    registry_tuple_valid = (
        bool(user_repo_raw)
        and _valid_huaidj_repo(user_repo)
        and _same_path(user_repo, installer_repo)
    )
    workdir_valid = _valid_huaidj_repo(workdir) and _same_path(workdir, installer_repo)

    if require_repo and not _valid_huaidj_repo(installer_repo):
        raise RuntimeError(f"Rendered HUAIDJ repo is missing or invalid: {installer_repo}")
    if workdir_valid:
        repo = workdir
        source = "validated_job_workdir"
    elif registry_tuple_valid:
        repo = user_repo
        source = "hkcu_runtime_tuple"
    else:
        repo = installer_repo
        source = "installer_rendered_defaults"

    if registry_tuple_valid:
        report_root = Path(user_values.get("HUAIDJ_REPORT_ROOT") or INSTALLER_REPORT_ROOT)
        python_exe = Path(user_values.get("HUAIDJ_PYTHON") or INSTALLER_PYTHON)
    else:
        report_root = INSTALLER_REPORT_ROOT
        python_exe = INSTALLER_PYTHON

    if require_repo and _path_is_within(report_root, repo):
        raise RuntimeError(f"HUAIDJ report root must stay outside the immutable repo: {report_root}")
    if require_python and not python_exe.is_file():
        raise RuntimeError(f"HUAIDJ Python is missing: {python_exe}")

    os.environ["HUAIDJ_REPO"] = str(repo)
    os.environ["HUAIDJ_PYTHON"] = str(python_exe)
    os.environ["HUAIDJ_REPORT_ROOT"] = str(report_root)
    return {
        "repo": repo,
        "python": python_exe,
        "report_root": report_root,
        "source": source,
    }
'''.strip()


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


# __HUAIDJ_RUNTIME_SSOT__
RUNTIME = _resolve_runtime_settings(require_repo=True)
HERMES_HOME = Path(os.environ.get("HERMES_HOME", r"C:\\Users\\pc\\AppData\\Local\\hermes"))
REPO = RUNTIME["repo"]
REPORT_ROOT = RUNTIME["report_root"]
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
    "-EnablePosterCloudBaseMigration",
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


# __HUAIDJ_RUNTIME_SSOT__
RUNTIME = _resolve_runtime_settings(require_repo=True)
REPO = RUNTIME["repo"]
REPORT_ROOT = RUNTIME["report_root"]
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


# __HUAIDJ_RUNTIME_SSOT__
RUNTIME = _resolve_runtime_settings(require_repo=True)
REPO = RUNTIME["repo"]
REPORT_ROOT = RUNTIME["report_root"]
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


# __HUAIDJ_RUNTIME_SSOT__
RUNTIME = _resolve_runtime_settings(require_repo=False)
REPORT_ROOT = RUNTIME["report_root"]
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
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


# __HUAIDJ_RUNTIME_SSOT__
RUNTIME = _resolve_runtime_settings(require_repo=True, require_python=True)
HERMES_HOME = Path(os.environ.get("HERMES_HOME", r"C:\\Users\\pc\\AppData\\Local\\hermes"))
REPO = RUNTIME["repo"]
PYTHON_EXE = RUNTIME["python"]
SANJI_ROOT = Path(os.environ.get("SANJI_ROOT", str(Path(os.environ.get("APPDATA", "")) / "sanji")))
SANJI_ARTICLES_ROOT = Path(os.environ.get("SANJI_HOT_ARTICLES_ROOT", r"E:\\sanji_hot\\articles"))
REPORT_ROOT = RUNTIME["report_root"]
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


def _load_run_summary_from_log(log_path: Path) -> dict:
    text = _tail(log_path, limit=32768)
    matches = list(re.finditer(r"summary:\\s*(.+?run_summary\\.json)\\s*$", text, flags=re.MULTILINE))
    if not matches:
        raise RuntimeError("AtlasV2 orchestrator did not report a run_summary.json path")
    summary_path = Path(matches[-1].group(1).strip())
    if not summary_path.is_file():
        raise RuntimeError(f"AtlasV2 run summary is missing: {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("schema_version") != "atlas_v2_sanji_import_run.v1":
        raise RuntimeError("AtlasV2 run summary schema is invalid")
    return summary


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
    try:
        summary = _load_run_summary_from_log(log_path)
    except Exception as exc:
        print(f"[BLOCKED] AtlasV2 exited zero without a valid terminal summary: {exc} log={log_path}")
        return 2
    status = str(summary.get("status") or "").strip()
    if status == "noop_no_new_articles":
        print(f"[NOOP] AtlasV2 has no new articles and no unresolved missing HTML. log={log_path}")
        return 0
    if status != "ok":
        print(f"[BLOCKED] AtlasV2 returned an unexpected zero-exit status={status!r}. log={log_path}")
        return 2
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


# __HUAIDJ_RUNTIME_SSOT__
RUNTIME = _resolve_runtime_settings(require_repo=True, require_python=True)
HERMES_HOME = Path(os.environ.get("HERMES_HOME", r"C:\\Users\\pc\\AppData\\Local\\hermes"))
REPO = RUNTIME["repo"]
PYTHON_EXE = str(RUNTIME["python"])
REPORT_ROOT = RUNTIME["report_root"]
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


# __HUAIDJ_RUNTIME_SSOT__
RUNTIME = _resolve_runtime_settings(require_repo=True, require_python=True)
HERMES_HOME = Path(os.environ.get("HERMES_HOME", r"C:\\Users\\pc\\AppData\\Local\\hermes"))
REPO = RUNTIME["repo"]
PYTHON_EXE = str(RUNTIME["python"])
REPORT_ROOT = RUNTIME["report_root"]
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

BASE_SCRIPT_TEMPLATES = dict(SCRIPT_TEMPLATES)


def _safe_rendered_path(value: Path) -> str:
    rendered = str(value.resolve(strict=False))
    if any(char in rendered for char in ('"', "\n", "\r")):
        raise ValueError(f"Unsupported character in rendered runtime path: {rendered!r}")
    return rendered


def installer_runtime_defaults() -> dict[str, Path]:
    """Return the non-secret defaults frozen into a launcher installation."""

    return {
        "repo": REPO.resolve(strict=False),
        "python": Path(os.environ.get("HUAIDJ_PYTHON") or sys.executable).resolve(strict=False),
        "report_root": Path(os.environ.get("HUAIDJ_REPORT_ROOT") or DEFAULT_REPORT_ROOT).resolve(strict=False),
    }


def render_script_template(
    rel: str,
    *,
    hermes_home: Path,
    repo: Path | None = None,
    python_exe: Path | None = None,
    report_root: Path | None = None,
) -> str:
    """Render one self-contained launcher with immutable runtime identity."""

    defaults = installer_runtime_defaults()
    selected_repo = (repo or defaults["repo"]).resolve(strict=False)
    selected_python = (python_exe or defaults["python"]).resolve(strict=False)
    selected_report_root = (report_root or defaults["report_root"]).resolve(strict=False)
    content = BASE_SCRIPT_TEMPLATES[rel].replace(RUNTIME_SSOT_MARKER, RUNTIME_SSOT_BLOCK)
    replacements = {
        "__HUAIDJ_INSTALLER_REPO__": _safe_rendered_path(selected_repo),
        "__HUAIDJ_INSTALLER_PYTHON__": _safe_rendered_path(selected_python),
        "__HUAIDJ_INSTALLER_REPORT_ROOT__": _safe_rendered_path(selected_report_root),
    }
    for token, value in replacements.items():
        content = content.replace(token, value)
    content = content.replace(r"C:\Users\pc\AppData\Local\hermes", str(hermes_home.resolve(strict=False)))
    return content


def render_script_templates(hermes_home: Path) -> dict[str, str]:
    defaults = installer_runtime_defaults()
    return {
        rel: render_script_template(
            rel,
            hermes_home=hermes_home,
            repo=defaults["repo"],
            python_exe=defaults["python"],
            report_root=defaults["report_root"],
        )
        for rel in BASE_SCRIPT_TEMPLATES
    }


# Keep this public mapping executable for existing offline contract tests.  The
# installer re-renders with its requested Hermes home before writing live files.
SCRIPT_TEMPLATES = render_script_templates(DEFAULT_HERMES_HOME)

SCRIPT_CONTRACT_TOKENS = {
    "huaidj/sanji_publish_afternoon.py": (
        "run_sanji_desktop_recent_export.ps1",
        "run_huaidj_sanji_daily_twice.ps1",
        "-Slot",
        "manual",
        "-SkipSanjiExport",
        "-EnablePosterCloudBaseMigration",
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
        "_load_run_summary_from_log",
        "[NOOP] AtlasV2 has no new articles",
        "No production promotion or service restart",
    ),
}

RUNTIME_SSOT_CONTRACT_TOKENS = (
    'HUAIDJ_LAUNCHER_SCHEMA = "huaidj_launcher_runtime_ssot.v1"',
    "INSTALLER_REPO = Path(",
    "INSTALLER_PYTHON = Path(",
    "INSTALLER_REPORT_ROOT = Path(",
    "def _read_user_runtime_inputs()",
    "def _resolve_runtime_settings(",
    'os.environ["HUAIDJ_REPO"] = str(repo)',
)
SCRIPT_CONTRACT_TOKENS = {
    rel: tuple(tokens) + RUNTIME_SSOT_CONTRACT_TOKENS
    for rel, tokens in SCRIPT_CONTRACT_TOKENS.items()
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
    return HermesCronApi(hermes_home, hermes_agent)


def _schedule_expr(job: dict[str, Any]) -> str:
    schedule = job.get("schedule")
    if isinstance(schedule, dict):
        return str(schedule.get("expr") or schedule.get("display") or "")
    return str(schedule or "")


def _new_canonical_job(name: str, spec: dict[str, Any], cron_module: Any) -> dict[str, Any]:
    parsed_schedule = cron_module.parse_schedule(spec["schedule"])
    now_fn = getattr(cron_module, "_hermes_now", None)
    now = now_fn().isoformat() if callable(now_fn) else datetime.now().astimezone().isoformat()
    return {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "prompt": None,
        "skills": [],
        "skill": None,
        "model": None,
        "provider": None,
        "provider_snapshot": None,
        "model_snapshot": None,
        "base_url": None,
        "script": spec["script"],
        "no_agent": True,
        "context_from": None,
        "schedule": parsed_schedule,
        "schedule_display": parsed_schedule.get("display", spec["schedule"]),
        "repeat": {"times": None, "completed": 0},
        "enabled": True,
        "state": "scheduled",
        "paused_at": None,
        "paused_reason": None,
        "created_at": now,
        "next_run_at": cron_module.compute_next_run(parsed_schedule),
        "last_run_at": None,
        "last_status": None,
        "last_error": None,
        "last_delivery_error": None,
        "deliver": spec.get("deliver", "weixin"),
        "origin": None,
        "enabled_toolsets": None,
        "workdir": str(REPO.resolve(strict=False)),
        "wrap_response": False,
    }


def _assign_if_different(job: dict[str, Any], key: str, value: Any, changed_fields: list[str]) -> None:
    current = job.get(key)
    equal = _same_path(Path(str(current)), Path(str(value))) if key == "workdir" and current and value else current == value
    if not equal:
        job[key] = value
        changed_fields.append(key)


def _plan_jobs(
    jobs: list[dict[str, Any]], cron_module: Any
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    """Return the full desired list while preserving IDs and runtime history."""

    actions: list[dict[str, Any]] = []
    changed = False
    by_name: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        by_name.setdefault(str(job.get("name") or ""), []).append(job)

    for name, spec in JOBS.items():
        expected_deliver = spec.get("deliver", "weixin")
        matches = by_name.get(name, [])
        if not matches:
            created = _new_canonical_job(name, spec, cron_module)
            jobs.append(created)
            by_name.setdefault(name, []).append(created)
            actions.append(
                {
                    "type": "job",
                    "name": name,
                    "existing_count": 0,
                    "schedule": spec["schedule"],
                    "script": spec["script"],
                    "deliver": expected_deliver,
                    "action": "create",
                    "job_id": created["id"],
                    "changed_fields": sorted(created.keys()),
                }
            )
            changed = True
            continue

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
        changed_fields: list[str] = []
        owned = {
            "deliver": expected_deliver,
            "script": spec["script"],
            "no_agent": True,
            "wrap_response": False,
            "state": "scheduled",
            "enabled": True,
            "workdir": str(REPO.resolve(strict=False)),
            "paused_at": None,
            "paused_reason": None,
        }
        for key, value in owned.items():
            _assign_if_different(job, key, value, changed_fields)
        if _schedule_expr(job) != spec["schedule"]:
            parsed_schedule = cron_module.parse_schedule(spec["schedule"])
            job["schedule"] = parsed_schedule
            job["schedule_display"] = parsed_schedule.get("display", spec["schedule"])
            job["next_run_at"] = cron_module.compute_next_run(parsed_schedule)
            changed_fields.extend(["schedule", "schedule_display", "next_run_at"])

        duplicate_actions: list[dict[str, Any]] = []
        for duplicate in duplicates:
            duplicate_reason = f"Duplicate of canonical Hermes job {job.get('id')}"
            duplicate_fields: list[str] = []
            for key, value in {
                "state": "paused",
                "enabled": False,
                "paused_reason": duplicate_reason,
            }.items():
                _assign_if_different(duplicate, key, value, duplicate_fields)
            duplicate_actions.append(
                {
                    "job_id": duplicate.get("id"),
                    "action": "pause" if duplicate_fields else "noop",
                    "changed_fields": duplicate_fields,
                }
            )
            if duplicate_fields:
                changed = True

        action_name = "update" if changed_fields else "noop"
        if changed_fields:
            changed = True
        actions.append(
            {
                "type": "job",
                "name": name,
                "existing_count": len(matches),
                "schedule": spec["schedule"],
                "script": spec["script"],
                "deliver": expected_deliver,
                "action": action_name,
                "job_id": job.get("id"),
                "changed_fields": changed_fields,
                "duplicate_job_ids": [row.get("id") for row in duplicates],
                "duplicate_actions": duplicate_actions,
                "paused_duplicate_job_ids": [
                    row["job_id"] for row in duplicate_actions if row["action"] == "pause"
                ],
            }
        )

    legacy_reason = "Superseded by HUAIDJ Sanji Wed 21:10 / Fri 20:10 off-peak weekly schedule"
    for name in sorted(LEGACY_JOB_NAMES):
        for job in by_name.get(name, []):
            changed_fields: list[str] = []
            for key, value in {
                "state": "paused",
                "enabled": False,
                "paused_reason": legacy_reason,
            }.items():
                _assign_if_different(job, key, value, changed_fields)
            if changed_fields:
                changed = True
            actions.append(
                {
                    "type": "legacy_job",
                    "name": name,
                    "job_id": job.get("id"),
                    "action": "pause" if changed_fields else "noop",
                    "changed_fields": changed_fields,
                }
            )
    return jobs, actions, changed


def write_scripts(hermes_home: Path, apply: bool) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    scripts_root = hermes_home / "scripts"
    rendered_templates = render_script_templates(hermes_home)
    for rel, rendered in rendered_templates.items():
        path = scripts_root / rel.replace("/", os.sep)
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        tokens = SCRIPT_CONTRACT_TOKENS.get(rel, ())
        forbidden = SCRIPT_FORBIDDEN_TOKENS.get(rel, ())
        contract_ok = (
            bool(old)
            and old == rendered
            and all(token in old for token in tokens)
            and not any(token in old for token in forbidden)
        )
        desired = rendered
        changed = old != rendered
        actions.append(
            {
                "type": "script",
                "path": str(path),
                "contract_ok": contract_ok,
                "changed": changed,
                "render_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
                "installer_repo": str(REPO.resolve(strict=False)),
            }
        )
        if apply and changed:
            _atomic_write_text(path, desired)
    return actions


def _managed_target_paths(hermes_home: Path) -> list[Path]:
    scripts_root = hermes_home / "scripts"
    return [hermes_home / "cron" / "jobs.json"] + [
        scripts_root / rel.replace("/", os.sep) for rel in sorted(SCRIPT_TEMPLATES)
    ]


def backup_plan(hermes_home: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for target in _managed_target_paths(hermes_home):
        exists = target.is_file()
        entries.append(
            {
                "target": str(target.resolve(strict=False)),
                "existed": exists,
                "sha256_before": _sha256_file(target) if exists else None,
                "restore_action": "copy_backup_to_target" if exists else "remove_target_if_created",
            }
        )
    return entries


def create_backup_snapshot(hermes_home: Path, backup_root: Path) -> dict[str, Any]:
    """Snapshot every managed target before the first apply write."""

    resolved_home = hermes_home.expanduser().resolve(strict=False)
    resolved_backup_root = backup_root.expanduser().resolve(strict=False)
    try:
        resolved_backup_root.relative_to(resolved_home)
    except ValueError:
        pass
    else:
        raise RuntimeError(f"Backup root must stay outside Hermes home: {resolved_backup_root}")

    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    snapshot = resolved_backup_root / f"huaidj-hermes-{stamp}-{uuid.uuid4().hex[:8]}"
    snapshot.mkdir(parents=True, exist_ok=False)
    entries = backup_plan(resolved_home)
    for entry in entries:
        target = Path(entry["target"])
        relative = target.relative_to(resolved_home)
        backup_path = snapshot / "files" / relative
        entry["backup"] = str(backup_path) if entry["existed"] else None
        if not entry["existed"]:
            continue
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup_path)
        copied_hash = _sha256_file(backup_path)
        if copied_hash != entry["sha256_before"]:
            raise RuntimeError(f"Backup hash mismatch for {target}")
        entry["backup_sha256"] = copied_hash

    manifest = {
        "schema_version": "huaidj_hermes_installer_restore_manifest.v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "hermes_home": str(resolved_home),
        "snapshot": str(snapshot),
        "requires_gateway_stopped_for_restore": True,
        "entries": entries,
    }
    manifest_path = snapshot / "restore_manifest.json"
    _atomic_write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    manifest["manifest"] = str(manifest_path)
    manifest["manifest_sha256"] = _sha256_file(manifest_path)
    return manifest


def _atomic_restore_file(source: Path, target: Path, expected_sha256: str) -> None:
    """Restore one verified backup without exposing a partially copied target."""

    if not source.is_file():
        raise FileNotFoundError(f"Hermes restore backup is missing: {source}")
    if _sha256_file(source) != expected_sha256:
        raise RuntimeError(f"Hermes restore backup hash mismatch: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".restore", dir=str(target.parent))
    os.close(fd)
    temporary_path = Path(temporary)
    try:
        shutil.copy2(source, temporary_path)
        if _sha256_file(temporary_path) != expected_sha256:
            raise RuntimeError(f"Hermes restore temporary hash mismatch: {target}")
        with temporary_path.open("r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary_path, target)
        if _sha256_file(target) != expected_sha256:
            raise RuntimeError(f"Hermes restored target hash mismatch: {target}")
    except BaseException:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise


def restore_backup_snapshot(backup: dict[str, Any]) -> dict[str, Any]:
    """Restore and verify every target named by a trusted installer snapshot."""

    report: dict[str, Any] = {
        "schema_version": "huaidj_hermes_installer_rollback.v1",
        "ok": False,
        "baseline_restored": False,
        "manifest_sha256_verified": False,
        "restored_targets": [],
        "removed_targets": [],
        "errors": [],
    }
    try:
        manifest_path = Path(str(backup.get("manifest") or "")).resolve(strict=False)
        expected_manifest_sha = str(backup.get("manifest_sha256") or "")
        if not manifest_path.is_file() or len(expected_manifest_sha) != 64:
            raise RuntimeError("Hermes restore manifest identity is incomplete")
        actual_manifest_sha = _sha256_file(manifest_path)
        if actual_manifest_sha != expected_manifest_sha:
            raise RuntimeError("Hermes restore manifest hash mismatch")
        report["manifest_sha256_verified"] = True
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != "huaidj_hermes_installer_restore_manifest.v1":
            raise RuntimeError("Hermes restore manifest schema is unsupported")
        hermes_home = Path(str(manifest.get("hermes_home") or "")).resolve(strict=False)
        snapshot = Path(str(manifest.get("snapshot") or "")).resolve(strict=False)
        if not _same_path(hermes_home, Path(str(backup.get("hermes_home") or ""))):
            raise RuntimeError("Hermes restore manifest home does not match the transaction")
        if not _same_path(snapshot, manifest_path.parent):
            raise RuntimeError("Hermes restore manifest snapshot path is inconsistent")

        entries = manifest.get("entries")
        if not isinstance(entries, list) or not entries:
            raise RuntimeError("Hermes restore manifest has no managed targets")
        expected_targets = {
            _normalized_path(path) for path in _managed_target_paths(hermes_home)
        }
        manifest_targets = {
            _normalized_path(Path(str(entry.get("target") or "")))
            for entry in entries
            if isinstance(entry, dict)
        }
        if manifest_targets != expected_targets:
            raise RuntimeError("Hermes restore manifest target set does not match the installer")

        for entry in entries:
            target = Path(str(entry.get("target") or "")).resolve(strict=False)
            try:
                target.relative_to(hermes_home)
                if bool(entry.get("existed")):
                    expected_sha = str(entry.get("sha256_before") or "")
                    backup_sha = str(entry.get("backup_sha256") or "")
                    source = Path(str(entry.get("backup") or "")).resolve(strict=False)
                    source.relative_to(snapshot / "files")
                    if len(expected_sha) != 64 or backup_sha != expected_sha:
                        raise RuntimeError(f"Hermes restore hash contract is invalid: {target}")
                    _atomic_restore_file(source, target, expected_sha)
                    report["restored_targets"].append(str(target))
                else:
                    if target.is_dir():
                        raise RuntimeError(f"Hermes restore target unexpectedly became a directory: {target}")
                    if target.exists() or target.is_symlink():
                        target.unlink()
                    report["removed_targets"].append(str(target))
            except (OSError, RuntimeError, ValueError) as exc:
                report["errors"].append(f"{target}: {type(exc).__name__}: {exc}")

        verification_errors: list[str] = []
        for entry in entries:
            target = Path(str(entry.get("target") or "")).resolve(strict=False)
            if bool(entry.get("existed")):
                expected_sha = str(entry.get("sha256_before") or "")
                if not target.is_file() or _sha256_file(target) != expected_sha:
                    verification_errors.append(f"restored hash mismatch: {target}")
            elif target.exists() or target.is_symlink():
                verification_errors.append(f"created target still exists: {target}")
        report["errors"].extend(verification_errors)
        report["baseline_restored"] = not report["errors"]
        report["ok"] = report["baseline_restored"]
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    return report


def apply_installation_transaction(
    *,
    hermes_home: Path,
    hermes_agent: Path,
    backup_root: Path,
) -> dict[str, Any]:
    """Apply launchers and jobs as one rollback-protected transaction."""

    api = load_api(hermes_home, hermes_agent)
    if not isinstance(api, HermesCronApi):
        raise RuntimeError("Hermes installer transaction requires the cross-process cron API")
    actions: list[dict[str, Any]] = []
    with api.transaction_lock():
        backup = create_backup_snapshot(hermes_home, backup_root)
        try:
            actions.extend(write_scripts(hermes_home, True))
            actions.extend(
                ensure_jobs(
                    hermes_home,
                    hermes_agent,
                    True,
                    already_locked=True,
                    api=api,
                )
            )
        except BaseException as exc:
            rollback = restore_backup_snapshot(backup)
            raise InstallerTransactionError(exc, backup=backup, rollback=rollback) from exc
    return {
        "backup": backup,
        "actions": actions,
        "rollback": None,
        "baseline_restored": None,
    }


def ensure_jobs(
    hermes_home: Path,
    hermes_agent: Path,
    apply: bool,
    *,
    already_locked: bool = False,
    api: HermesCronApi | None = None,
) -> list[dict[str, Any]]:
    api = api or load_api(hermes_home, hermes_agent)
    if isinstance(api, HermesCronApi):
        return api.reconcile(_plan_jobs, apply=apply, already_locked=already_locked)

    if already_locked:
        raise RuntimeError("Legacy Hermes cron adapters cannot prove the installer transaction lock")

    # Compatibility path for tests/older embedders that replace load_api with
    # the former three-function tuple. Production always uses HermesCronApi.
    create_job, load_jobs, update_job = api
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
    parser.add_argument(
        "--backup-root",
        default=str(DEFAULT_BACKUP_ROOT),
        help="External directory for the pre-apply restore snapshot.",
    )
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    hermes_home = Path(args.hermes_home)
    hermes_agent = Path(args.hermes_agent)
    backup_root = Path(args.backup_root)
    runtime_defaults = installer_runtime_defaults()
    report: dict[str, Any] = {
        "schema_version": "huaidj_sanji_hermes_job_installer.v3",
        "applied": bool(args.apply),
        "repo": str(REPO),
        "hermes_home": str(hermes_home),
        "hermes_agent": str(hermes_agent),
        "hermes_runtime": str(hermes_agent),
        "runtime_defaults": {name: str(value) for name, value in runtime_defaults.items()},
        "actions": [],
        "backup_plan": backup_plan(hermes_home),
    }
    try:
        script_plan = write_scripts(hermes_home, False)
        job_plan = ensure_jobs(hermes_home, hermes_agent, False)
        would_change = any(bool(action.get("changed")) for action in script_plan) or any(
            action.get("action") in {"create", "update", "pause"}
            or any(
                duplicate.get("action") == "pause"
                for duplicate in action.get("duplicate_actions", [])
            )
            for action in job_plan
        )
        report["would_change"] = would_change
        if args.apply and would_change:
            transaction = apply_installation_transaction(
                hermes_home=hermes_home,
                hermes_agent=hermes_agent,
                backup_root=backup_root,
            )
            report["backup"] = transaction["backup"]
            report["actions"].extend(transaction["actions"])
            report["rollback"] = transaction["rollback"]
            report["baseline_restored"] = transaction["baseline_restored"]
            report["changed"] = True
        else:
            report["actions"].extend(script_plan)
            report["actions"].extend(job_plan)
            report["changed"] = False
            report["backup"] = None
        report["ok"] = True
    except InstallerTransactionError as exc:
        report["ok"] = False
        report["error"] = str(exc)
        report["backup"] = exc.backup
        report["rollback"] = exc.rollback
        report["baseline_restored"] = bool(exc.rollback.get("baseline_restored"))
    except Exception as exc:
        report["ok"] = False
        report["error"] = str(exc)

    if args.json_out:
        out = Path(args.json_out)
        _atomic_write_text(out, json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
