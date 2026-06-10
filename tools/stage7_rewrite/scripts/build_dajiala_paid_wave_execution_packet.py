#!/usr/bin/env python3
"""Build a bounded paid Dajiala execution packet without calling the API.

This packet reflects explicit paid authorization, selects the next queue slice
after previously consumed wave files, and writes a secret-free PowerShell runner
that expects DAJIALA_API_KEY/JZL_API_KEY to already exist in the environment.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_QUEUE = Path("reports/dajiala_paid_prioritized_queue_20260516/dajiala_paid_prioritized_queue.jsonl")
DEFAULT_USED_QUEUES = [
    Path("reports/dajiala_paid_prioritized_queue_20260516/dajiala_paid_next100.jsonl"),
    Path("reports/dajiala_paid_prioritized_queue_20260516/dajiala_paid_next100_wave02.jsonl"),
    Path("reports/dajiala_paid_prioritized_queue_20260516/dajiala_paid_next100_wave03.jsonl"),
    Path("reports/dajiala_paid_prioritized_queue_20260516/dajiala_paid_next100_wave04.jsonl"),
]
DEFAULT_OUT_DIR = Path("reports/dajiala_paid_wave05_execution_packet_20260517")
SCHEMA_VERSION = "stage7_dajiala_paid_wave_execution_packet.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for paid wave execution packet: {path}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def row_key(row: dict[str, Any]) -> str:
    return str(row.get("article_uid") or row.get("article_id") or row.get("url") or row.get("source_url") or "").strip()


def has_key(env: dict[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    if (source.get("DAJIALA_API_KEY") or source.get("JZL_API_KEY") or "").strip():
        return True
    if env is not None:
        return False
    return windows_persistent_env_has_key("DAJIALA_API_KEY") or windows_persistent_env_has_key("JZL_API_KEY")


def windows_persistent_env_has_key(name: str) -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg
    except ImportError:
        return False
    for root_key, subkey in (
        (winreg.HKEY_CURRENT_USER, "Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    ):
        try:
            with winreg.OpenKey(root_key, subkey) as handle:
                value, _value_type = winreg.QueryValueEx(handle, name)
        except OSError:
            continue
        if str(value or "").strip():
            return True
    return False


def select_next_rows(queue: list[dict[str, Any]], used_rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    used = {row_key(row) for row in used_rows if row_key(row)}
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in queue:
        key = row_key(row)
        if not key or key in used or key in seen:
            continue
        url = str(row.get("url") or row.get("source_url") or "").strip()
        if not url.startswith("http"):
            continue
        selected.append(row)
        seen.add(key)
        if len(selected) >= limit:
            break
    return selected


def write_runner(path: Path, *, manifest_path: Path, out_dir: Path, status_path: Path, result_log_path: Path) -> None:
    script = f'''$ErrorActionPreference = "Stop"
Set-Location "C:\\code\\githubstar\\wechathtmldownload"

foreach ($name in @("DAJIALA_API_KEY", "JZL_API_KEY")) {{
  if (-not [Environment]::GetEnvironmentVariable($name, "Process")) {{
    $persistentValue = [Environment]::GetEnvironmentVariable($name, "User")
    if (-not $persistentValue) {{
      $persistentValue = [Environment]::GetEnvironmentVariable($name, "Machine")
    }}
    if ($persistentValue) {{
      [Environment]::SetEnvironmentVariable($name, $persistentValue, "Process")
    }}
  }}
}}

if (-not $env:DAJIALA_API_KEY -and -not $env:JZL_API_KEY) {{
  throw "DAJIALA_API_KEY/JZL_API_KEY missing from environment"
}}

npm run dajiala-repair-archive-batch -- `
  --manifestPath {manifest_path.as_posix()} `
  --outDir {out_dir.as_posix()} `
  --statusPath {status_path.as_posix()} `
  --resultLogPath {result_log_path.as_posix()} `
  --concurrency 1 `
  --requestDelayMs 1200 `
  --resume

exit $LASTEXITCODE
'''
    path.write_text(script, encoding="utf-8")


def build_packet(
    *,
    queue_path: Path,
    used_queue_paths: list[Path],
    out_dir: Path,
    wave_id: str,
    limit: int,
    unit_cost: float,
    paid_authorized: bool,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    queue = read_jsonl(queue_path)
    used_rows: list[dict[str, Any]] = []
    used_counts: dict[str, int] = {}
    for path in used_queue_paths:
        rows = read_jsonl(path)
        used_rows.extend(rows)
        used_counts[str(path)] = len(rows)
    selected = select_next_rows(queue, used_rows, limit)
    queue_out = out_dir / f"dajiala_paid_{wave_id}.jsonl"
    archive_out = Path(f"reports/dajiala_paid_{wave_id}_archive_20260517")
    status_path = archive_out / "dajiala-repair-status.json"
    result_log_path = archive_out / "dajiala-repair-results.jsonl"
    runner = out_dir / f"run_dajiala_{wave_id}_repair.ps1"
    write_jsonl(queue_out, selected)
    write_runner(
        runner,
        manifest_path=Path("tools/stage7_rewrite") / queue_out,
        out_dir=Path("tools/stage7_rewrite") / archive_out,
        status_path=Path("tools/stage7_rewrite") / status_path,
        result_log_path=Path("tools/stage7_rewrite") / result_log_path,
    )
    key_present = has_key(env)
    estimated_cost = round(len(selected) * unit_cost, 4)
    next_paid_wave_allowed = paid_authorized and key_present and bool(selected)
    blockers = []
    if not paid_authorized:
        blockers.append("paid Dajiala is not authorized")
    if not key_present:
        blockers.append("DAJIALA_API_KEY/JZL_API_KEY missing from runtime environment")
    if not selected:
        blockers.append("no unconsumed signed long-link candidate rows selected")
    decision = (
        "dajiala_paid_wave_execution_ready"
        if next_paid_wave_allowed
        else "dajiala_paid_wave_execution_ready_key_missing"
        if paid_authorized and not key_present and bool(selected)
        else "dajiala_paid_wave_execution_blocked"
    )
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": decision,
        "paid_authorized": paid_authorized,
        "runtime_key_present": key_present,
        "next_paid_wave_allowed": next_paid_wave_allowed,
        "paid_api_called": False,
        "balance_query_executed": False,
        "queue_path": str(queue_path),
        "used_queue_paths": [str(path) for path in used_queue_paths],
        "used_counts": used_counts,
        "input_rows": len(queue),
        "selected_rows": len(selected),
        "wave_id": wave_id,
        "unit_cost": unit_cost,
        "estimated_wave_cost": estimated_cost,
        "selected_queue_path": str(queue_out),
        "runner_path": str(runner),
        "archive_out_dir": str(archive_out),
        "status_path": str(status_path),
        "result_log_path": str(result_log_path),
        "blockers": blockers,
        "stop_rules": [
            "stop if amount_not_enough/recharge appears",
            "stop if success rate after this wave is below 0.30",
            "stop if image-bearing assets among successes fall below 0.80",
            "resume only; do not retry failed rows blindly",
        ],
        "safety": {
            "reports_only": True,
            "key_written_to_files": False,
            "paid_api_called": False,
            "balance_query_executed": False,
            "source_archive_write_executed": False,
            "db_vector_graph_mem0_write": False,
            "d_scan": False,
            "publish": False,
        },
        "writes": "queue_and_runner_only",
    }
    write_json(out_dir / "dajiala_paid_wave_execution_packet.json", packet)
    write_markdown(out_dir / "dajiala_paid_wave_execution_packet.md", packet)
    return packet


def write_markdown(path: Path, packet: dict[str, Any]) -> None:
    lines = [
        "# Dajiala Paid Wave Execution Packet",
        "",
        f"- generated_at: `{packet['generated_at']}`",
        f"- decision: `{packet['decision']}`",
        f"- paid_authorized: `{packet['paid_authorized']}`",
        f"- runtime_key_present: `{packet['runtime_key_present']}`",
        f"- next_paid_wave_allowed: `{packet['next_paid_wave_allowed']}`",
        f"- selected_rows: `{packet['selected_rows']}`",
        f"- estimated_wave_cost: `{packet['estimated_wave_cost']}`",
        f"- selected_queue_path: `{packet['selected_queue_path']}`",
        f"- runner_path: `{packet['runner_path']}`",
        "",
        "## Blockers",
        "",
    ]
    if packet["blockers"]:
        lines.extend(f"- {item}" for item in packet["blockers"])
    else:
        lines.append("- none")
    lines.extend(["", "## Stop Rules", ""])
    lines.extend(f"- {item}" for item in packet["stop_rules"])
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(packet["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--used-queue", action="append", type=Path, default=[])
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--wave-id", default="wave05")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--unit-cost", type=float, default=0.03)
    parser.add_argument("--paid-authorized", action="store_true")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    packet = build_packet(
        queue_path=args.queue,
        used_queue_paths=args.used_queue or DEFAULT_USED_QUEUES,
        out_dir=args.out_dir,
        wave_id=args.wave_id,
        limit=args.limit,
        unit_cost=args.unit_cost,
        paid_authorized=args.paid_authorized,
    )
    print(
        json.dumps(
            {
                "ok": packet["ok"],
                "decision": packet["decision"],
                "paid_authorized": packet["paid_authorized"],
                "runtime_key_present": packet["runtime_key_present"],
                "selected_rows": packet["selected_rows"],
                "estimated_wave_cost": packet["estimated_wave_cost"],
                "summary": str(args.out_dir / "dajiala_paid_wave_execution_packet.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
