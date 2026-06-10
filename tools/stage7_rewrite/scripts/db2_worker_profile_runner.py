from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


SCRIPTS_DIR = Path("/db2-scripts")
ADAPTER_DIR = Path("/workspace/tools/stage7_rewrite/scripts")
OUTLINK_EXPAND_ADAPTER = ADAPTER_DIR / "db2_outlink_expand_spool_adapter.py"
AVATAR_ADAPTER = ADAPTER_DIR / "db2_avatar_spool_adapter.py"
IDENTITY_SOURCE_PROVIDER_ADAPTER = ADAPTER_DIR / "db2_identity_source_provider_acquisition_adapter.py"
IDENTITY_SOURCE_PROVIDER_COMMAND = ["python3", "-u", IDENTITY_SOURCE_PROVIDER_ADAPTER.as_posix(), "--limit", "130"]

WORKER_COMMANDS = {
    "marathon": ["python3", "-u", str(SCRIPTS_DIR / "swarm_marathon_engine.py")],
    "swarm_monitor": ["python3", "-u", str(SCRIPTS_DIR / "swarm_monitor_v2.py"), "--daemon"],
    "linktree": ["python3", "-u", str(SCRIPTS_DIR / "linktree_deep_traversal.py"), "--daemon"],
    "outlink_expand": ["python3", "-u", OUTLINK_EXPAND_ADAPTER.as_posix(), "--legacy-script", (SCRIPTS_DIR / "outlink_expand_worker.py").as_posix(), "--phase", "linktree", "--limit", "200", "--sleep", "0.8"],
    "outlink_expand_linktree": ["python3", "-u", OUTLINK_EXPAND_ADAPTER.as_posix(), "--legacy-script", (SCRIPTS_DIR / "outlink_expand_worker.py").as_posix(), "--phase", "linktree", "--limit", "200", "--sleep", "0.8"],
    "outlink_expand_shorturl": ["python3", "-u", OUTLINK_EXPAND_ADAPTER.as_posix(), "--legacy-script", (SCRIPTS_DIR / "outlink_expand_worker.py").as_posix(), "--phase", "shorturl", "--limit", "200", "--sleep", "0.8"],
    "sc_deep": ["python3", "-u", str(SCRIPTS_DIR / "sc_deep_worker.py"), "--max-profiles", "2000"],
    "yt_deep": ["python3", "-u", str(SCRIPTS_DIR / "yt_deep_worker.py")],
    "domestic": ["python3", "-u", str(SCRIPTS_DIR / "domestic_worker.py")],
    "avatar_dl": ["python3", "-u", AVATAR_ADAPTER.as_posix(), "--legacy-script", (SCRIPTS_DIR / "avatar_dl_worker.py").as_posix(), "--platform", "soundcloud", "--limit", "500"],
    "identity_source_provider": IDENTITY_SOURCE_PROVIDER_COMMAND,
    "identity_source_provider_acquisition": IDENTITY_SOURCE_PROVIDER_COMMAND,
    "maigret": ["python3", "-u", str(SCRIPTS_DIR / "maigret_discover_worker.py")],
    "bc_deep": ["python3", "-u", str(SCRIPTS_DIR / "bc_deep_worker.py"), "--limit", "10"],
    "ra_deep": ["python3", "-u", str(SCRIPTS_DIR / "scrape_ra_artist_deep.py"), "--limit", "10"],
    "nuclear_fission": ["python3", "-u", str(SCRIPTS_DIR / "nuclear_fission_engine.py"), "--rounds", "1", "--limit", "10"],
}

PROFILE_WORKERS = {
    "safe": [
        "marathon",
        "swarm_monitor",
        "linktree",
        "outlink_expand_linktree",
        "outlink_expand_shorturl",
        "sc_deep",
        "yt_deep",
        "domestic",
        "avatar_dl",
    ],
    "steady": [
        "marathon",
        "swarm_monitor",
        "linktree",
        "outlink_expand_linktree",
        "outlink_expand_shorturl",
        "sc_deep",
        "yt_deep",
        "domestic",
        "avatar_dl",
        "maigret",
    ],
    "experimental": [],
}

BANNED_WORKERS = {"searxng_discovery"}
EXPERIMENTAL_WORKERS = {"bc_deep", "ra_deep", "nuclear_fission"}
SPOOL_READY_WORKERS = {
    "outlink_expand",
    "outlink_expand_linktree",
    "outlink_expand_shorturl",
    "avatar_dl",
    "identity_source_provider",
    "identity_source_provider_acquisition",
}


def resolve_workers(profile: str, workers: list[str] | None = None, *, only: bool = False) -> list[str]:
    if profile not in PROFILE_WORKERS:
        raise ValueError(f"unknown profile: {profile}")
    selected = [] if only else list(PROFILE_WORKERS[profile])
    if only and not workers:
        raise ValueError("only-worker requires at least one worker")
    if workers:
        selected.extend(workers)
    errors = validate_workers(profile, selected)
    if errors:
        raise ValueError("; ".join(errors))
    return selected


def validate_workers(profile: str, workers: list[str]) -> list[str]:
    errors: list[str] = []
    for worker in workers:
        if worker in BANNED_WORKERS:
            errors.append(f"banned: {worker}")
        elif worker not in WORKER_COMMANDS:
            errors.append(f"unknown: {worker}")
        elif profile != "experimental" and worker in EXPERIMENTAL_WORKERS:
            errors.append(f"experimental_only: {worker}")
    return errors


def override_command_limit(command: list[str], limit: int | None) -> list[str]:
    if limit is None:
        return list(command)
    if limit <= 0:
        raise ValueError("limit must be positive")
    updated = list(command)
    for flag in ("--limit", "--max-profiles"):
        if flag in updated:
            index = updated.index(flag)
            if index + 1 >= len(updated):
                raise ValueError(f"{flag} is missing a value")
            updated[index + 1] = str(limit)
            return updated
    updated.extend(["--limit", str(limit)])
    return updated


def build_plan(profile: str, workers: list[str] | None = None, *, only: bool = False, limit: int | None = None) -> list[dict]:
    return [
        {"worker": name, "command": override_command_limit(WORKER_COMMANDS[name], limit), "spool_ready": name in SPOOL_READY_WORKERS}
        for name in resolve_workers(profile, workers, only=only)
    ]


def validate_execute_plan(plan: list[dict], *, write_mode: str) -> list[str]:
    if write_mode != "spool":
        return []
    return [f"not_spool_migrated: {item['worker']}" for item in plan if not item.get("spool_ready")]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DB2 worker profile runner")
    parser.add_argument("--profile", choices=sorted(PROFILE_WORKERS), default="safe")
    parser.add_argument("--worker", action="append", default=[])
    parser.add_argument("--only-worker", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--detach", action="store_true", help="Start workers and return immediately. Default execute mode waits and preserves logs.")
    return parser.parse_args(argv)


def env_truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def execute_detached(plan: list[dict]) -> dict:
    processes = []
    for item in plan:
        process = subprocess.Popen(item["command"])
        processes.append({"worker": item["worker"], "pid": process.pid, "command": item["command"]})
    return {"dry_run": False, "execution_mode": "detach", "started": processes, "returncode": 0}


def execute_wait(plan: list[dict]) -> dict:
    results = []
    returncode = 0
    for item in plan:
        started_at = now_utc()
        print(json.dumps({"event": "worker_start", "worker": item["worker"], "command": item["command"], "started_at": started_at}, ensure_ascii=False), flush=True)
        completed = subprocess.run(item["command"], check=False)
        finished_at = now_utc()
        result = {
            "worker": item["worker"],
            "command": item["command"],
            "started_at": started_at,
            "finished_at": finished_at,
            "returncode": completed.returncode,
        }
        results.append(result)
        print(json.dumps({"event": "worker_finish", **result}, ensure_ascii=False), flush=True)
        if completed.returncode != 0:
            returncode = completed.returncode
            break
    return {"dry_run": False, "execution_mode": "wait", "results": results, "returncode": returncode}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.worker and args.only_worker:
        raise SystemExit("--worker and --only-worker are mutually exclusive")
    only = bool(args.only_worker)
    plan = build_plan(args.profile, args.only_worker if only else args.worker, only=only, limit=args.limit)
    execute = args.execute or env_truthy(os.environ.get("DB2_WORKER_EXECUTE"))
    if not execute:
        print(json.dumps({"dry_run": True, "profile": args.profile, "workers": plan}, ensure_ascii=False, indent=2))
        return 0
    write_mode = os.environ.get("DB2_WRITE_MODE", "spool").strip().lower()
    execution_errors = validate_execute_plan(plan, write_mode=write_mode)
    if execution_errors:
        print(json.dumps({"dry_run": False, "profile": args.profile, "errors": execution_errors}, ensure_ascii=False, indent=2))
        return 3
    summary = execute_detached(plan) if args.detach else execute_wait(plan)
    summary["profile"] = args.profile
    print(json.dumps(summary, ensure_ascii=False))
    return int(summary.get("returncode", 0))


if __name__ == "__main__":
    raise SystemExit(main())
