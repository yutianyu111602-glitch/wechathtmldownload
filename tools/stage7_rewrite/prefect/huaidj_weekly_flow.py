#!/usr/bin/env python3
"""Prefect orchestration layer for the HUAIDJ weekly mini-program pipeline.

This flow intentionally wraps the existing scripts instead of reimplementing
pipeline logic. Validators remain the publishing gate:

- no source-backed date means no publish
- uncertain lineup stays empty and the mini-program points users to the source
- backend deploy and mini-program upload are opt-in parameters
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from prefect import flow, get_run_logger, task


REPO_ROOT = Path(os.environ.get("HUAIDJ_REPO_ROOT", Path(__file__).resolve().parents[3]))
LONGRUN_ROOT = Path(os.environ.get("HUAIDJ_LONGRUN_ROOT", r"E:\weekly_activity_pipeline\longrun"))
REPORT_ROOT = Path(
    os.environ.get("HUAIDJ_REPORT_ROOT", r"F:\DevData\HuaidjRuntime\state\reports")
) / "prefect_weekly_flow"
DEFAULT_RUNTIME_DATA_ROOT = Path(
    r"F:\DevData\HuaidjRuntime\state\weekly_activity_cloudrun\data"
)

WIN_RELEASE_SCRIPT = REPO_ROOT / "tools" / "stage7_rewrite" / "weekly_activity_next_week_pipeline.ps1"
SCRIPTS_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "scripts"
CROSS_SOURCE_AUDIT = SCRIPTS_DIR / "audit_weekly_cross_source_conflicts.py"
LINEUP_ADDRESS_TIME_AUDIT = SCRIPTS_DIR / "audit_weekly_lineup_address_time.py"
SOURCE_DATA_COMPARE_AUDIT = SCRIPTS_DIR / "audit_weekly_source_data_compare.py"
DEFAULT_WSL_PIPELINE = "/home/pc/scripts/huaidj-weekly-pipeline.sh"
NON_PRODUCTION_DIR_MARKERS = (
    "SMOKE",
    "TEST",
    "TMP",
    "DEBUG",
    "SAMPLE",
    "EXPERIMENT",
)


@dataclass
class CommandResult:
    label: str
    command: list[str]
    cwd: str
    dry_run: bool
    returncode: int
    elapsed_s: float
    stdout_tail: str = ""
    stderr_tail: str = ""


def _tail(text: str, limit: int = 4000) -> str:
    if not text:
        return ""
    return text[-limit:]


def _powershell_exe() -> str:
    return shutil.which("pwsh") or shutil.which("powershell") or "powershell"


def _run_command(
    label: str,
    command: list[str],
    cwd: Path | None = None,
    dry_run: bool = False,
    extra_env: dict[str, str] | None = None,
) -> CommandResult:
    logger = get_run_logger()
    workdir = str(cwd or REPO_ROOT)
    logger.info("%s: %s", label, " ".join(shlex.quote(str(part)) for part in command))
    if dry_run:
        return CommandResult(label, command, workdir, True, 0, 0.0)

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("DEEPSEEK_THINKING_TYPE", "disabled")
    env.setdefault("DEEPSEEK_MODEL", "deepseek-v4-flash")
    if extra_env:
        env.update(extra_env)

    started = time.time()
    proc = subprocess.run(
        [str(part) for part in command],
        cwd=workdir,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    elapsed = time.time() - started
    result = CommandResult(
        label=label,
        command=[str(part) for part in command],
        cwd=workdir,
        dry_run=False,
        returncode=proc.returncode,
        elapsed_s=round(elapsed, 3),
        stdout_tail=_tail(proc.stdout),
        stderr_tail=_tail(proc.stderr),
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"{label} failed with exit={proc.returncode}\n"
            f"stdout_tail={result.stdout_tail}\n"
            f"stderr_tail={result.stderr_tail}"
        )
    return result


def _latest_dir(prefix: str, required: tuple[str, ...]) -> Path | None:
    if not LONGRUN_ROOT.exists():
        return None
    candidates: list[Path] = []
    for path in LONGRUN_ROOT.glob(f"{prefix}*"):
        if not path.is_dir():
            continue
        upper_name = path.name.upper()
        if any(marker in upper_name for marker in NON_PRODUCTION_DIR_MARKERS):
            continue
        if all((path / item).exists() for item in required):
            candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _resolve_dir(value: str, prefix: str, required: tuple[str, ...]) -> Path:
    if value:
        path = Path(value)
        if path.exists():
            return path
        raise FileNotFoundError(f"Configured path does not exist: {path}")
    latest = _latest_dir(prefix, required)
    if latest is None:
        raise FileNotFoundError(f"No {prefix} directory found under {LONGRUN_ROOT}")
    return latest


def _windows_path_to_wsl(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    rest = resolved.as_posix().split(":", 1)[1].lstrip("/")
    if not drive:
        raise ValueError(f"Cannot convert non-drive path to WSL path: {resolved}")
    return f"/mnt/{drive}/{rest}"


def _authoritative_current_release(value: str = "") -> Path:
    configured_current = str(value or os.environ.get("HUAIDJ_CURRENT_RELEASE_DIR") or "").strip()
    if configured_current:
        return Path(configured_current)
    configured_data = str(os.environ.get("HUAIDJ_CLOUDRUN_DATA_ROOT") or "").strip()
    return Path(configured_data or DEFAULT_RUNTIME_DATA_ROOT) / "current_release"


@task(name="preflight")
def preflight(
    api_dir: str,
    release_dir: str,
    current_release_dir: str,
    build_release: bool,
    deploy_backend: bool,
    upload_miniprogram: bool,
) -> dict[str, Any]:
    required_paths = [
        WIN_RELEASE_SCRIPT,
        CROSS_SOURCE_AUDIT,
        LINEUP_ADDRESS_TIME_AUDIT,
    ]
    if deploy_backend:
        required_paths.append(REPO_ROOT / "services" / "weekly_activity_cloudrun" / "scripts" / "bake_and_deploy.py")
        authoritative = _authoritative_current_release(current_release_dir).resolve()
        try:
            authoritative.relative_to(REPO_ROOT.resolve())
        except ValueError:
            pass
        else:
            raise ValueError("Production current_release must be outside the source checkout")
        for name in ("current.json", "manifest.json"):
            if not (authoritative / name).is_file():
                raise FileNotFoundError(f"Authoritative current_release is incomplete: {authoritative / name}")
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing required pipeline files: {missing}")

    env_presence = {
        "DEEPSEEK_API_KEY": bool(os.environ.get("DEEPSEEK_API_KEY")),
        "MPTEXT_AUTH_KEY": bool(os.environ.get("MPTEXT_AUTH_KEY")),
        "DAJIALA_API_KEY_or_JZL_API_KEY": bool(os.environ.get("DAJIALA_API_KEY") or os.environ.get("JZL_API_KEY")),
        "TCB_SECRET_ID": bool(os.environ.get("TCB_SECRET_ID")),
        "TCB_SECRET_KEY": bool(os.environ.get("TCB_SECRET_KEY")),
    }
    return {
        "repo": str(REPO_ROOT),
        "longrun_root": str(LONGRUN_ROOT),
        "api_dir_param": api_dir,
        "release_dir_param": release_dir,
        "current_release_dir": str(_authoritative_current_release(current_release_dir)),
        "build_release": build_release,
        "deploy_backend": deploy_backend,
        "upload_miniprogram": upload_miniprogram,
        "env_presence_only": env_presence,
    }


@task(name="build_future_release")
def build_future_release(
    dry_run: bool,
    week_start: str,
    window_days: int,
    article_since_date: str,
    poster_ocr_limit: int,
    poster_ocr_max_images: int,
    poster_ocr_timeout_sec: int,
    max_items: int,
) -> dict[str, Any]:
    command: list[str] = [
        _powershell_exe(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(WIN_RELEASE_SCRIPT),
        "-WindowDays",
        str(window_days),
        "-MaxItems",
        str(max_items),
        "-PosterOcrLimit",
        str(poster_ocr_limit),
        "-PosterOcrMaxImages",
        str(poster_ocr_max_images),
        "-PosterOcrTimeoutSec",
        str(poster_ocr_timeout_sec),
        "-SkipUpload",
    ]
    if dry_run:
        command.append("-DryRun")
    if week_start:
        command.extend(["-WeekStart", week_start])
    if article_since_date:
        command.extend(["-ArticleSinceDate", article_since_date])
    result = _run_command("weekly_release_build", command, cwd=REPO_ROOT, dry_run=False)
    return asdict(result)


@task(name="resolve_release_inputs")
def resolve_release_inputs(api_dir: str, release_dir: str) -> dict[str, str]:
    resolved_api = _resolve_dir(api_dir, "WEEKLY_ACTIVITY_MINIPROGRAM_API", ("current.json", "manifest.json"))
    resolved_release = _resolve_dir(release_dir, "WEEKLY_ACTIVITY_MINIPROGRAM_RELEASE", ("current.json", "manifest.json"))
    return {
        "api_dir": str(resolved_api),
        "release_dir": str(resolved_release),
        "item_count": str(_count_current_items(resolved_api / "current.json")),
    }


def _count_current_items(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        items = data.get("items") or data.get("events") or []
        return len(items) if isinstance(items, list) else 0
    return 0


@task(name="quality_audits")
def quality_audits(
    api_dir: str,
    dry_run: bool,
    run_source_compare: bool,
    pack_dir: str,
    window_start: str,
    window_days: int,
) -> list[dict[str, Any]]:
    api_path = Path(api_dir)
    current_json = api_path / "current.json"
    if not current_json.exists():
        raise FileNotFoundError(f"Missing current.json for quality audit: {current_json}")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)

    commands = [
        (
            "cross_source_conflicts",
            [
                sys.executable,
                str(CROSS_SOURCE_AUDIT),
                "--input",
                str(current_json),
                "--strict",
                "--fail-on-raw-duplicates",
            ],
        ),
        (
            "lineup_address_time",
            [
                sys.executable,
                str(LINEUP_ADDRESS_TIME_AUDIT),
                "--api-dir",
                str(api_path),
                "--report",
                str(REPORT_ROOT / f"lineup_address_time_{timestamp}.json"),
                "--strict",
            ],
        ),
    ]
    if run_source_compare:
        if not pack_dir or not window_start:
            raise ValueError("run_source_compare requires both pack_dir and window_start")
        commands.append(
            (
                "source_data_compare",
                [
                    sys.executable,
                    str(SOURCE_DATA_COMPARE_AUDIT),
                    "--api-dir",
                    str(api_path),
                    "--pack-dir",
                    pack_dir,
                    "--window-start",
                    window_start,
                    "--window-days",
                    str(window_days),
                    "--report",
                    str(REPORT_ROOT / f"source_data_compare_{timestamp}.json"),
                    "--strict",
                ],
            )
        )

    results = []
    for label, command in commands:
        results.append(asdict(_run_command(label, command, cwd=REPO_ROOT, dry_run=dry_run)))
    return results


@task(name="backend_publish")
def backend_publish(
    release_dir: str,
    current_release_dir: str,
    dry_run: bool,
    deploy_backend: bool,
    upload_miniprogram: bool,
) -> dict[str, Any]:
    if not deploy_backend:
        return {
            "skipped": True,
            "reason": "deploy_backend=false",
            "upload_miniprogram": upload_miniprogram,
        }
    if not shutil.which("wsl.exe"):
        raise RuntimeError("wsl.exe is required for the existing OpenClaw production script")
    wsl_release = _windows_path_to_wsl(Path(release_dir))
    authoritative = _authoritative_current_release(current_release_dir)
    wsl_current = _windows_path_to_wsl(authoritative)
    wsl_data_root = _windows_path_to_wsl(authoritative.parent)
    command = (
        f"HUAIDJ_CURRENT_RELEASE_DIR={shlex.quote(wsl_current)} "
        f"HUAIDJ_CLOUDRUN_DATA_ROOT={shlex.quote(wsl_data_root)} "
        f"bash {shlex.quote(DEFAULT_WSL_PIPELINE)} --release-dir {shlex.quote(wsl_release)}"
    )
    if not upload_miniprogram:
        command += " --skip-upload"
    result = _run_command(
        "openclaw_backend_pipeline",
        ["wsl.exe", "bash", "-lc", command],
        cwd=REPO_ROOT,
        dry_run=dry_run,
    )
    return asdict(result)


@task(name="write_prefect_report")
def write_prefect_report(payload: dict[str, Any]) -> str:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_ROOT / f"prefect_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(report_path)


@flow(name="huaidj-weekly-publication")
def huaidj_weekly_publication_flow(
    dry_run: bool = True,
    build_release: bool = False,
    deploy_backend: bool = False,
    upload_miniprogram: bool = False,
    api_dir: str = "",
    release_dir: str = "",
    current_release_dir: str = "",
    week_start: str = "",
    window_days: int = 15,
    article_since_date: str = "",
    poster_ocr_limit: int = 0,
    poster_ocr_max_images: int = 0,
    poster_ocr_timeout_sec: int = 20,
    max_items: int = 10000,
    run_source_compare: bool = False,
    pack_dir: str = "",
    window_start: str = "",
) -> dict[str, Any]:
    """Run the public weekly pipeline through Prefect gates."""

    preflight_result = preflight(
        api_dir,
        release_dir,
        current_release_dir,
        build_release,
        deploy_backend,
        upload_miniprogram,
    )
    build_result: dict[str, Any] | None = None
    if build_release:
        build_result = build_future_release(
            dry_run=dry_run,
            week_start=week_start,
            window_days=window_days,
            article_since_date=article_since_date,
            poster_ocr_limit=poster_ocr_limit,
            poster_ocr_max_images=poster_ocr_max_images,
            poster_ocr_timeout_sec=poster_ocr_timeout_sec,
            max_items=max_items,
        )

    resolved = resolve_release_inputs(api_dir, release_dir)
    audits = quality_audits(
        api_dir=resolved["api_dir"],
        dry_run=dry_run,
        run_source_compare=run_source_compare,
        pack_dir=pack_dir,
        window_start=window_start,
        window_days=window_days,
    )
    backend = backend_publish(
        release_dir=resolved["release_dir"],
        current_release_dir=current_release_dir,
        dry_run=dry_run,
        deploy_backend=deploy_backend,
        upload_miniprogram=upload_miniprogram,
    )

    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "preflight": preflight_result,
        "build": build_result,
        "resolved": resolved,
        "audits": audits,
        "backend": backend,
    }
    payload["report_path"] = write_prefect_report(payload)
    return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or serve the HUAIDJ weekly Prefect flow.")
    parser.add_argument("--execute", action="store_true", help="Run commands. Default is dry-run.")
    parser.add_argument("--build-release", action="store_true", help="Run weekly_activity_next_week_pipeline.ps1.")
    parser.add_argument("--deploy-backend", action="store_true", help="Run the existing OpenClaw backend deploy script.")
    parser.add_argument("--upload-miniprogram", action="store_true", help="Allow mini-program upload in the backend script.")
    parser.add_argument("--api-dir", default="")
    parser.add_argument("--release-dir", default="")
    parser.add_argument("--current-release-dir", default="")
    parser.add_argument("--week-start", default="")
    parser.add_argument("--window-days", type=int, default=15)
    parser.add_argument("--article-since-date", default="")
    parser.add_argument("--poster-ocr-limit", type=int, default=0)
    parser.add_argument("--poster-ocr-max-images", type=int, default=0)
    parser.add_argument("--poster-ocr-timeout-sec", type=int, default=20)
    parser.add_argument("--max-items", type=int, default=10000)
    parser.add_argument("--run-source-compare", action="store_true")
    parser.add_argument("--pack-dir", default="")
    parser.add_argument("--window-start", default="")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    huaidj_weekly_publication_flow(
        dry_run=not args.execute,
        build_release=args.build_release,
        deploy_backend=args.deploy_backend,
        upload_miniprogram=args.upload_miniprogram,
        api_dir=args.api_dir,
        release_dir=args.release_dir,
        current_release_dir=args.current_release_dir,
        week_start=args.week_start,
        window_days=args.window_days,
        article_since_date=args.article_since_date,
        poster_ocr_limit=args.poster_ocr_limit,
        poster_ocr_max_images=args.poster_ocr_max_images,
        poster_ocr_timeout_sec=args.poster_ocr_timeout_sec,
        max_items=args.max_items,
        run_source_compare=args.run_source_compare,
        pack_dir=args.pack_dir,
        window_start=args.window_start,
    )


if __name__ == "__main__":
    main()
