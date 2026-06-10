#!/usr/bin/env python3
"""Audit OpenClaw/HUAIDJ scheduled runners against the S46 freeze boundary.

Report-only. This does not run OpenClaw/weekly pipelines, deploy CloudRun,
upload the mini-program, read credentials, call providers, or mutate data. It
only inspects scheduler text/safe systemd show output for active deploy-capable
entries that must remain disabled while S46 is active.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_openclaw_scheduler_freeze_audit_s95_20260601"
)

FORBIDDEN_CRON_PATTERNS: dict[str, re.Pattern[str]] = {
    "active_stable_deploy_cron": re.compile(r"\bhuaidj-weekly-openclaw-stable\.sh\b"),
    "active_weekly_pipeline_cron": re.compile(r"\bhuaidj-weekly-pipeline\.sh\b"),
    "active_legacy_daily_pipeline_cron": re.compile(r"\brun_daily_pipeline\.sh\b"),
    "active_openclaw_daily_publish_cron": re.compile(r"\brun_openclaw_weekly_daily_publish\.ps1\b"),
    "active_weekly_release_builder_cron": re.compile(r"\bweekly_activity_next_week_pipeline\.ps1\b"),
}

FORBIDDEN_SYSTEMD_PATTERNS: dict[str, re.Pattern[str]] = {
    "systemd_stable_deploy_runner": re.compile(r"\bhuaidj-weekly-openclaw-stable\.sh\b"),
    "systemd_weekly_pipeline_runner": re.compile(r"\bhuaidj-weekly-pipeline\.sh\b"),
    "systemd_legacy_daily_pipeline_runner": re.compile(r"\brun_daily_pipeline\.sh\b"),
}

ALLOWED_MARKERS = {
    "huaidj-daily-download.sh",
    "huaidj-weekly-healthcheck.sh",
    "docker-watchdog.sh",
    "qdrant-backup.sh",
    "huaidj-daily-pipeline.timer",
    "huaidj-qr-check.timer",
    "run_daily_pipeline_resilient.sh",
}

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*=\s*[^ \t\r\n]+"),
]


def redact(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda m: f"{m.group(1)}=REDACTED" if m.lastindex else "REDACTED", redacted)
    return redacted


def is_active_cron_line(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def classify_crontab(crontab_text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    active_entries: list[dict[str, Any]] = []
    for line_number, line in enumerate(crontab_text.splitlines(), start=1):
        if not is_active_cron_line(line):
            continue
        safe_line = redact(line.strip())
        allowed = sorted(marker for marker in ALLOWED_MARKERS if marker in line)
        active_entries.append({"line_number": line_number, "line": safe_line, "allowed_markers": allowed})
        for code, pattern in FORBIDDEN_CRON_PATTERNS.items():
            if pattern.search(line):
                findings.append(
                    {
                        "surface": "crontab",
                        "code": code,
                        "line_number": line_number,
                        "line": safe_line,
                    }
                )
    return active_entries, findings


def classify_systemd_text(systemd_text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    observed: list[dict[str, Any]] = []
    for line_number, line in enumerate(systemd_text.splitlines(), start=1):
        if not line.strip():
            continue
        safe_line = redact(line.strip())
        allowed = sorted(marker for marker in ALLOWED_MARKERS if marker in line)
        observed.append({"line_number": line_number, "line": safe_line, "allowed_markers": allowed})
        for code, pattern in FORBIDDEN_SYSTEMD_PATTERNS.items():
            if not pattern.search(line):
                continue
            if code == "systemd_legacy_daily_pipeline_runner" and "run_daily_pipeline_resilient.sh" in line:
                continue
            findings.append(
                {
                    "surface": "systemd",
                    "code": code,
                    "line_number": line_number,
                    "line": safe_line,
                }
            )
    return observed, findings


def audit_scheduler_state(
    *,
    crontab_text: str,
    systemd_timers_text: str = "",
    systemd_service_show_text: str = "",
    systemd_timer_show_text: str = "",
    source: str = "provided_text",
) -> dict[str, Any]:
    active_cron_entries, cron_findings = classify_crontab(crontab_text)
    observed_systemd, systemd_findings = classify_systemd_text(
        "\n".join([systemd_timers_text, systemd_service_show_text, systemd_timer_show_text])
    )
    findings = cron_findings + systemd_findings
    decision = (
        "weekly_openclaw_scheduler_freeze_audit_passed"
        if not findings
        else "weekly_openclaw_scheduler_freeze_audit_findings"
    )
    return {
        "schema_version": "weekly_openclaw_scheduler_freeze_audit.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "decision": decision,
        "source": source,
        "finding_count": len(findings),
        "findings": findings,
        "active_cron_entry_count": len(active_cron_entries),
        "active_cron_entries": active_cron_entries,
        "observed_systemd_line_count": len(observed_systemd),
        "observed_systemd_lines": observed_systemd,
        "boundary": {
            "s46_freeze_active": True,
            "forbidden_active_cron_codes": sorted(FORBIDDEN_CRON_PATTERNS),
            "forbidden_systemd_codes": sorted(FORBIDDEN_SYSTEMD_PATTERNS),
            "allowed_markers": sorted(ALLOWED_MARKERS),
            "report_only": True,
            "pipeline_run": False,
            "deploy_upload_review": False,
            "provider_or_geocode_call": False,
            "secrets_redacted": True,
        },
    }


def run_wsl_readonly(command: str, timeout_sec: int) -> str:
    completed = subprocess.run(
        ["wsl.exe", "-d", "Ubuntu", "--", "bash", "-lc", command],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
    )
    return completed.stdout


def collect_live_wsl(timeout_sec: int) -> dict[str, str]:
    return {
        "crontab_text": run_wsl_readonly("crontab -l 2>/dev/null || true", timeout_sec),
        "systemd_timers_text": run_wsl_readonly(
            "systemctl --user list-timers --all --no-pager 2>/dev/null | "
            "grep -E 'huaidj|weekly|openclaw' || true",
            timeout_sec,
        ),
        "systemd_service_show_text": run_wsl_readonly(
            "systemctl --user show huaidj-daily-pipeline.service "
            "-p FragmentPath -p ExecStart -p Result -p ExecMainStatus -p ActiveState -p SubState "
            "--no-pager 2>/dev/null || true",
            timeout_sec,
        ),
        "systemd_timer_show_text": run_wsl_readonly(
            "systemctl --user show huaidj-daily-pipeline.timer "
            "-p ActiveState -p Unit -p NextElapseUSecRealtime --no-pager 2>/dev/null || true",
            timeout_sec,
        ),
    }


def read_text(path: Path | None) -> str:
    return "" if path is None else path.read_text(encoding="utf-8", errors="replace")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Weekly OpenClaw Scheduler Freeze Audit",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Source: `{report['source']}`",
        f"- Finding count: `{report['finding_count']}`",
        f"- Active cron entries: `{report['active_cron_entry_count']}`",
        f"- Observed systemd lines: `{report['observed_systemd_line_count']}`",
        "- S46 freeze active: `true`",
        "- Pipeline run: `false`",
        "- Deploy/upload/review: `false`",
        "- Provider/geocode call: `false`",
        "- Secrets redacted: `true`",
        "",
        "## Findings",
        "",
    ]
    if not report["findings"]:
        lines.append("No active deploy-capable OpenClaw/HUAIDJ scheduler entries were found.")
    else:
        for finding in report["findings"]:
            lines.append(
                f"- `{finding['code']}` on `{finding['surface']}` line `{finding['line_number']}`: `{finding['line']}`"
            )

    lines.extend(["", "## Active Crontab Entries", ""])
    if not report["active_cron_entries"]:
        lines.append("- None observed.")
    else:
        for entry in report["active_cron_entries"]:
            markers = ",".join(entry["allowed_markers"]) or "none"
            lines.append(f"- line `{entry['line_number']}` markers=`{markers}`: `{entry['line']}`")

    lines.extend(["", "## Systemd Observations", ""])
    if not report["observed_systemd_lines"]:
        lines.append("- None observed.")
    else:
        for entry in report["observed_systemd_lines"]:
            markers = ",".join(entry["allowed_markers"]) or "none"
            lines.append(f"- line `{entry['line_number']}` markers=`{markers}`: `{entry['line']}`")

    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This audit is report-only. It reads scheduler state only. It does not run OpenClaw/weekly pipelines, deploy CloudRun, upload or submit the mini-program, rebuild releases, read credentials, call Tencent/Amap/MiMo/DeepSeek APIs, write coordinates, mutate DB/graph/vector/public pointers, restart services, or scan broad disks.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(report: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_openclaw_scheduler_freeze_audit.json"
    md_path = out_dir / "weekly_openclaw_scheduler_freeze_audit.md"
    write_json(json_path, report)
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-wsl", action="store_true", help="Collect safe read-only scheduler state from WSL Ubuntu.")
    parser.add_argument("--crontab-file", type=Path)
    parser.add_argument("--systemd-timers-file", type=Path)
    parser.add_argument("--systemd-service-show-file", type=Path)
    parser.add_argument("--systemd-timer-show-file", type=Path)
    parser.add_argument("--timeout-sec", type=int, default=8)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.live_wsl:
        payload = collect_live_wsl(args.timeout_sec)
        source = "live_wsl_readonly"
    else:
        payload = {
            "crontab_text": read_text(args.crontab_file),
            "systemd_timers_text": read_text(args.systemd_timers_file),
            "systemd_service_show_text": read_text(args.systemd_service_show_file),
            "systemd_timer_show_text": read_text(args.systemd_timer_show_file),
        }
        source = "provided_files"

    report = audit_scheduler_state(source=source, **payload)
    paths = write_reports(report, args.out_dir)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "finding_count": report["finding_count"],
                "active_cron_entry_count": report["active_cron_entry_count"],
                "json": str(paths["json"]),
                "markdown": str(paths["markdown"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["finding_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
