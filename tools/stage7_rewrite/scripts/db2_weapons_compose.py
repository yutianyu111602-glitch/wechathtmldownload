from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


COMPOSE_FILE = Path("tools/stage7_rewrite/db2_weapons/compose.yaml")
WSL_DOCKER_BIN = "/usr/bin/docker"

KNOWN_WORKERS = {
    "marathon",
    "swarm_monitor",
    "linktree",
    "outlink_expand",
    "outlink_expand_linktree",
    "outlink_expand_shorturl",
    "sc_deep",
    "yt_deep",
    "domestic",
    "avatar_dl",
    "identity_source_provider",
    "identity_source_provider_acquisition",
    "maigret",
    "bc_deep",
    "ra_deep",
    "nuclear_fission",
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


def resolve_workers(profile: str) -> list[str]:
    if profile not in PROFILE_WORKERS:
        raise ValueError(f"unknown profile: {profile}")
    return list(PROFILE_WORKERS[profile])


def validate_worker_names(workers: list[str]) -> list[str]:
    errors: list[str] = []
    for worker in workers:
        if worker in BANNED_WORKERS:
            errors.append(f"banned: {worker}")
        elif worker not in KNOWN_WORKERS:
            errors.append(f"unknown: {worker}")
    return errors


def validate_workers_for_profile(profile: str, workers: list[str]) -> list[str]:
    errors = validate_worker_names(workers)
    if errors:
        return errors
    for worker in workers:
        if profile != "experimental" and worker in EXPERIMENTAL_WORKERS:
            errors.append(f"experimental_only: {worker}")
        elif profile == "experimental" and worker not in EXPERIMENTAL_WORKERS:
            errors.append(f"not_experimental: {worker}")
    return errors


def path_exists(path: Path) -> bool:
    return path.exists()


def docker_binary() -> str:
    configured = os.environ.get("DB2_DOCKER_BIN", "").strip()
    if configured:
        return configured
    wsl_docker = Path(WSL_DOCKER_BIN)
    if path_exists(Path("/proc/version")) and path_exists(wsl_docker):
        return WSL_DOCKER_BIN
    return "docker"


def compose_prefix() -> str:
    return f"{docker_binary()} compose -f {COMPOSE_FILE.as_posix()}"


def build_compose_command(action: str) -> str:
    prefix = compose_prefix()
    commands = {
        "readonly-probe": f"{prefix} --profile readonly run --rm db2-reconcile",
        "safe-up": f"{prefix} --profile safe up -d db2-light-workers",
        "steady-up": f"{prefix} --profile steady up -d db2-light-workers",
        "browser-up": f"{prefix} --profile browser up -d db2-lightpanda",
        "writer-up": f"{prefix} --profile writer up -d db2-writer",
        "experimental-smoke": f"{prefix} --profile experimental run --rm db2-browser-tools",
        "experimental-bc-smoke": f"{prefix} --profile experimental run --rm db2-browser-tools python tools/stage7_rewrite/scripts/db2_worker_profile_runner.py --profile experimental --worker bc_deep",
        "experimental-ra-smoke": f"{prefix} --profile experimental run --rm db2-browser-tools python tools/stage7_rewrite/scripts/db2_worker_profile_runner.py --profile experimental --worker ra_deep",
        "experimental-nuclear-smoke": f"{prefix} --profile experimental run --rm db2-browser-tools python tools/stage7_rewrite/scripts/db2_worker_profile_runner.py --profile experimental --worker nuclear_fission",
        "mount-doctor": f"{prefix} --profile safe run --rm --no-deps db2-light-workers python tools/stage7_rewrite/scripts/db2_container_mount_doctor.py",
        "ps": f"{prefix} ps",
        "ops-shell": f"{prefix} --profile readonly run --rm db2-ops-shell",
    }
    if action not in commands:
        raise ValueError(f"unknown action: {action}")
    return commands[action]


def build_worker_run_command(profile: str, workers: list[str], *, limit: int | None = None) -> str:
    if not workers:
        raise ValueError("at least one worker is required")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    if profile not in PROFILE_WORKERS:
        raise ValueError(f"unknown profile: {profile}")
    errors = validate_workers_for_profile(profile, workers)
    if errors:
        raise ValueError("; ".join(errors))
    prefix = compose_prefix()
    service = "db2-browser-tools" if profile == "experimental" else "db2-light-workers"
    worker_args = " ".join(f"--only-worker {worker}" for worker in workers)
    limit_arg = f" --limit {limit}" if limit is not None else ""
    return (
        f"{prefix} --profile {profile} run --rm {service} "
        f"python tools/stage7_rewrite/scripts/db2_worker_profile_runner.py "
        f"--profile {profile} {worker_args}{limit_arg}"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print DB2 weapons Docker Compose commands")
    parser.add_argument(
        "action",
        choices=[
            "readonly-probe",
            "safe-up",
            "steady-up",
            "browser-up",
            "writer-up",
            "experimental-smoke",
            "experimental-bc-smoke",
            "experimental-ra-smoke",
            "experimental-nuclear-smoke",
            "mount-doctor",
            "ops-shell",
            "profile-workers",
            "run-worker",
        ],
    )
    parser.add_argument("--profile", choices=sorted(PROFILE_WORKERS), default="safe")
    parser.add_argument("--worker", action="append", default=[])
    parser.add_argument("--limit", type=int)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.action == "profile-workers":
        print(
            json.dumps(
                {
                    "profile": args.profile,
                    "workers": [
                        {"worker": worker, "spool_ready": worker in SPOOL_READY_WORKERS}
                        for worker in resolve_workers(args.profile)
                    ],
                },
                ensure_ascii=False,
            )
        )
    elif args.action == "run-worker":
        print(build_worker_run_command(args.profile, args.worker, limit=args.limit))
    else:
        print(build_compose_command(args.action))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
