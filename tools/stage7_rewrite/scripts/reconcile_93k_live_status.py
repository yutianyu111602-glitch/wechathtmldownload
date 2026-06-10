#!/usr/bin/env python3
"""Reconcile stale 93k watchdog red-hold snapshots with current live evidence.

The archived 93k status reader intentionally preserves historical watchdog and
orchestrator state. This companion script is report-only: it reads that snapshot,
checks current local process/disk signals, reads the current fullmap/quality
evidence, and writes a fresh reconciliation report.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_STATUS_JSON = Path("reports/pipeline_status_93k_20260517_after_fullmap/PIPELINE_STATUS_LATEST.json")
DEFAULT_FULLMAP_SUMMARY = Path("reports/fullmap_47k_ready_text_authok_20260517_summary/summary.json")
DEFAULT_QUALITY_SUMMARY = Path(
    "reports/fullmap_47k_ready_text_authok_20260517_quality_checkpoint/QUALITY_CHECKPOINT_SUMMARY.json"
)
DEFAULT_OUT_DIR = Path("reports/pipeline_status_93k_live_reconcile_20260517")
DEFAULT_PATTERNS = [
    "stage7_deepseek_flash_pilot",
    "run_parallel_flash",
    "run_hybrid_pipeline",
    "run-93k",
    "fullmap",
    "full93k",
]
SECRETISH_RE = re.compile(r"(?i)(api[_-]?key|token|secret|password|cookie)=([^\\s;]+)")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def nested_get(value: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def redact_command_line(text: str, limit: int = 320) -> str:
    redacted = SECRETISH_RE.sub(lambda match: f"{match.group(1)}=<redacted>", text or "")
    return redacted[:limit]


def normalize_powershell_json(stdout: str) -> list[dict[str, Any]]:
    stripped = stdout.strip()
    if not stripped:
        return []
    parsed = json.loads(stripped)
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return [row for row in parsed if isinstance(row, dict)]
    return []


def collect_live_processes(patterns: list[str]) -> dict[str, Any]:
    regex = "|".join(re.escape(item) for item in patterns)
    command = r"""
$ErrorActionPreference = 'Stop'
$rx = $env:STAGE7_RECONCILE_PROCESS_REGEX
$selfPid = [int]$env:STAGE7_RECONCILE_SELF_PID
Get-CimInstance Win32_Process |
  Where-Object {
    $_.ProcessId -ne $PID -and
    $_.ProcessId -ne $selfPid -and
    $_.CommandLine -and
    ($_.CommandLine -match $rx)
  } |
  Select-Object ProcessId, Name, CreationDate, CommandLine |
  ConvertTo-Json -Depth 4
"""
    env = os.environ.copy()
    env["STAGE7_RECONCILE_PROCESS_REGEX"] = regex
    env["STAGE7_RECONCILE_SELF_PID"] = str(os.getpid())
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env=env,
        )
    except Exception as exc:  # pragma: no cover - platform/runtime fallback
        return {"ok": False, "error": str(exc), "processes": []}
    if completed.returncode != 0:
        return {"ok": False, "error": completed.stderr.strip(), "processes": []}
    rows = []
    for item in normalize_powershell_json(completed.stdout):
        cmd = str(item.get("CommandLine") or "")
        matched = [pattern for pattern in patterns if re.search(re.escape(pattern), cmd, flags=re.IGNORECASE)]
        rows.append(
            {
                "pid": item.get("ProcessId"),
                "name": item.get("Name"),
                "created": item.get("CreationDate"),
                "matched_patterns": matched,
                "command_line_excerpt": redact_command_line(cmd),
            }
        )
    return {"ok": True, "processes": rows}


def collect_d_disk_busy() -> dict[str, Any]:
    command = r"""
$ErrorActionPreference = 'Stop'
$samples = @()
try {
  $raw = (Get-Counter -Counter '\LogicalDisk(D:)\% Disk Time' -SampleInterval 1 -MaxSamples 3).CounterSamples
  foreach ($sample in $raw) { $samples += [math]::Round($sample.CookedValue, 2) }
} catch {
  $raw = (Get-Counter -Counter '\PhysicalDisk(*)\% Disk Time' -SampleInterval 1 -MaxSamples 3).CounterSamples |
    Where-Object { $_.InstanceName -match 'd:' -or $_.InstanceName -eq 'd' }
  foreach ($sample in $raw) { $samples += [math]::Round($sample.CookedValue, 2) }
}
[pscustomobject]@{
  ok = $true
  samples = $samples
  max = (($samples | Measure-Object -Maximum).Maximum)
} | ConvertTo-Json -Depth 3
"""
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
        )
    except Exception as exc:  # pragma: no cover - platform/runtime fallback
        return {"ok": False, "error": str(exc), "samples": [], "max": None}
    if completed.returncode != 0:
        return {"ok": False, "error": completed.stderr.strip(), "samples": [], "max": None}
    rows = normalize_powershell_json(completed.stdout)
    if not rows:
        return {"ok": False, "error": "no disk counter samples returned", "samples": [], "max": None}
    row = rows[0]
    samples = row.get("samples")
    if isinstance(samples, (int, float)):
        samples = [samples]
    samples = [float(item) for item in samples] if isinstance(samples, list) else []
    max_value = row.get("max")
    if max_value is None and samples:
        max_value = max(samples)
    return {"ok": True, "samples": samples, "max": max_value}


def fullmap_complete(summary: dict[str, Any]) -> bool:
    return (
        int(summary.get("rows") or 0) > 0
        and int(summary.get("pending_total") or 0) == 0
        and int(summary.get("failed_total") or 0) == 0
        and float(summary.get("progress_pct") or 0.0) >= 100.0
        and set((summary.get("shard_status_counts") or {}).keys()) <= {"complete"}
    )


def quality_green(summary: dict[str, Any]) -> bool:
    return nested_get(summary, ("audit", "verdict")) == "GREEN"


def build_report(
    *,
    status: dict[str, Any],
    fullmap: dict[str, Any],
    quality: dict[str, Any],
    live_processes: dict[str, Any],
    disk_busy: dict[str, Any],
    disk_busy_threshold: float,
) -> dict[str, Any]:
    historical_red_hold = (
        nested_get(status, ("watchdog", "status")) == "red_hold"
        or nested_get(status, ("orchestrator", "status")) == "red_hold"
    )
    live_process_count = len(live_processes.get("processes") or [])
    disk_max = disk_busy.get("max")
    disk_probe_ok = bool(disk_busy.get("ok"))
    disk_ok = disk_probe_ok and disk_max is not None and float(disk_max) < disk_busy_threshold
    is_fullmap_complete = fullmap_complete(fullmap)
    is_quality_green = quality_green(quality)

    blockers: list[str] = []
    if live_process_count:
        blockers.append("live_forbidden_processes_present")
    if not disk_ok:
        blockers.append("d_disk_busy_probe_not_green")
    if not is_fullmap_complete:
        blockers.append("fullmap_not_complete")
    if not is_quality_green:
        blockers.append("quality_checkpoint_not_green")

    if blockers:
        decision = "live_status_blocked"
    elif historical_red_hold:
        decision = "stale_red_hold_overridden_by_live_green"
    else:
        decision = "live_status_green"

    return {
        "schema_version": "stage7_93k_live_reconcile.v1",
        "generated_at": now_iso(),
        "decision": decision,
        "historical": {
            "watchdog_status": nested_get(status, ("watchdog", "status")),
            "watchdog_updated_at": nested_get(status, ("watchdog", "updated_at")),
            "orchestrator_status": nested_get(status, ("orchestrator", "status")),
            "orchestrator_updated_at": nested_get(status, ("orchestrator", "updated_at")),
            "historical_red_hold": historical_red_hold,
        },
        "live": {
            "process_probe_ok": bool(live_processes.get("ok")),
            "live_forbidden_process_count": live_process_count,
            "live_forbidden_processes": live_processes.get("processes") or [],
            "disk_probe_ok": disk_probe_ok,
            "d_disk_time_samples": disk_busy.get("samples") or [],
            "d_disk_time_max": disk_max,
            "disk_busy_threshold": disk_busy_threshold,
            "d_disk_ok": disk_ok,
        },
        "fullmap": {
            "rows": fullmap.get("rows"),
            "selected_total": fullmap.get("selected_total"),
            "pending_total": fullmap.get("pending_total"),
            "failed_total": fullmap.get("failed_total"),
            "progress_pct": fullmap.get("progress_pct"),
            "shard_status_counts": fullmap.get("shard_status_counts"),
            "complete": is_fullmap_complete,
        },
        "quality": {
            "verdict": nested_get(quality, ("audit", "verdict")),
            "red_flags": nested_get(quality, ("audit", "red_flags"), []),
            "amber_flags": nested_get(quality, ("audit", "amber_flags"), []),
            "green": is_quality_green,
        },
        "blockers": blockers,
        "safe_next_action": (
            "continue_consumer_release_pack_and_production_readiness_refresh"
            if not blockers
            else "resolve_live_blockers_before_mutating_full_pipeline"
        ),
        "writes": "report-only; no D: scan, no extraction/vector/db/paid API writes",
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    live = report["live"]
    fullmap = report["fullmap"]
    quality = report["quality"]
    lines = [
        "# Stage7 93k Live Status Reconcile",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- blockers: `{', '.join(report['blockers']) if report['blockers'] else 'none'}`",
        "",
        "## Historical Snapshot",
        "",
        f"- watchdog_status: `{report['historical']['watchdog_status']}`",
        f"- watchdog_updated_at: `{report['historical']['watchdog_updated_at']}`",
        f"- orchestrator_status: `{report['historical']['orchestrator_status']}`",
        f"- orchestrator_updated_at: `{report['historical']['orchestrator_updated_at']}`",
        "",
        "## Live Evidence",
        "",
        f"- live_forbidden_process_count: `{live['live_forbidden_process_count']}`",
        f"- d_disk_time_samples: `{live['d_disk_time_samples']}`",
        f"- d_disk_time_max: `{live['d_disk_time_max']}`",
        f"- d_disk_ok: `{live['d_disk_ok']}`",
        "",
        "## Current Fullmap Evidence",
        "",
        f"- rows: `{fullmap['rows']}`",
        f"- pending_total: `{fullmap['pending_total']}`",
        f"- failed_total: `{fullmap['failed_total']}`",
        f"- progress_pct: `{fullmap['progress_pct']}`",
        f"- complete: `{fullmap['complete']}`",
        "",
        "## Quality",
        "",
        f"- verdict: `{quality['verdict']}`",
        f"- green: `{quality['green']}`",
        "",
        "## Safety",
        "",
        f"- writes: `{report['writes']}`",
        f"- safe_next_action: `{report['safe_next_action']}`",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status-json", type=Path, default=DEFAULT_STATUS_JSON)
    parser.add_argument("--fullmap-summary", type=Path, default=DEFAULT_FULLMAP_SUMMARY)
    parser.add_argument("--quality-summary", type=Path, default=DEFAULT_QUALITY_SUMMARY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--disk-busy-threshold", type=float, default=80.0)
    parser.add_argument("--process-pattern", action="append", default=None)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    patterns = args.process_pattern or DEFAULT_PATTERNS
    report = build_report(
        status=read_json(args.status_json),
        fullmap=read_json(args.fullmap_summary),
        quality=read_json(args.quality_summary),
        live_processes=collect_live_processes(patterns),
        disk_busy=collect_d_disk_busy(),
        disk_busy_threshold=args.disk_busy_threshold,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "pipeline_status_93k_live_reconcile.json", report)
    write_markdown(args.out_dir / "pipeline_status_93k_live_reconcile.md", report)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "blockers": report["blockers"],
                "live_forbidden_process_count": report["live"]["live_forbidden_process_count"],
                "d_disk_time_max": report["live"]["d_disk_time_max"],
                "fullmap_complete": report["fullmap"]["complete"],
                "quality_green": report["quality"]["green"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not report["blockers"] else 2


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
