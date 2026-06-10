from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import db2_worker_profile_runner


DEFAULT_LIVE_DB = Path("/home/pc/swarm_data/atlas_swarm_data.sqlite")
DEFAULT_CACHE_DB = Path("/home/pc/swarm_data/cache/db2_sidecar_cache.sqlite")
DEFAULT_SPOOL_DIR = Path("/home/pc/swarm_data/write_spool")


def build_policy() -> dict[str, Any]:
    safe_spool_workers = [
        worker
        for worker in db2_worker_profile_runner.PROFILE_WORKERS["safe"]
        if worker in db2_worker_profile_runner.SPOOL_READY_WORKERS
    ]
    non_spool_by_profile = {
        profile: [
            worker
            for worker in workers
            if worker not in db2_worker_profile_runner.SPOOL_READY_WORKERS
        ]
        for profile, workers in db2_worker_profile_runner.PROFILE_WORKERS.items()
    }
    return {
        "policy": "db2_outlink_policy_s132",
        "version": 1,
        "read_only": True,
        "would_write": False,
        "runtime_boundary": {
            "live_db": str(DEFAULT_LIVE_DB),
            "live_db_storage": "WSL ext4",
            "spool_dir": str(DEFAULT_SPOOL_DIR),
            "cache_db": str(DEFAULT_CACHE_DB),
            "d_drive_allowed": False,
            "cookie_mount_default": False,
            "searxng_allowed": False,
        },
        "allowed_readonly_commands": [
            "db2ctl status",
            "db2ctl health",
            "db2ctl health --lock-holders",
            "db2ctl preflight",
            "db2ctl existing-data",
            "db2ctl schedule --profile safe",
            "db2ctl schedule --profile safe --only-worker outlink_expand_linktree",
            "db2ctl schedule --profile safe --only-worker outlink_expand_shorturl",
            "db2ctl schedule --profile safe --only-worker avatar_dl",
            "db2ctl recovery stale-running-plan",
            "db2ctl recovery stale-running-reset --snapshot-path SNAPSHOT",
            "db2ctl cache status",
            "db2ctl cache seed --limit 1000",
            "db2ctl writer status",
            "db2ctl compose mount-doctor",
            "db2ctl policy",
            "db2ctl contracts list",
            "db2ctl contracts show CONTRACT_ID",
            "db2ctl contracts verify-all",
        ],
        "allowed_worker_commands_after_gates": [
            f"db2ctl up safe --worker {worker}" for worker in safe_spool_workers
        ],
        "human_confirmation_required": [
            "DB2_WORKER_EXECUTE=1",
            "DB2_WRITER_EXECUTE=1",
            "db2ctl cache seed --execute",
            "db2ctl writer once --execute",
            "db2ctl recovery stale-running-reset --execute --snapshot-path SNAPSHOT --confirm reset-stale-running",
            "db2ctl snapshot NAME --execute",
            "db2ctl checkpoint truncate --execute",
        ],
        "denied_commands": [
            "python3 swarm_restart_v3.py --workers all",
            "db2ctl up all",
            "db2ctl up searxng",
            "db2ctl delete-wal",
            "db2ctl sql-write",
            "db2ctl read-cookies",
            "blind stale running reset without snapshot proof",
            "rm -f /home/pc/swarm_data/*.sqlite-wal",
            "rm -f /home/pc/swarm_data/*.sqlite-shm",
        ],
        "profiles": {
            profile: {
                "workers": list(workers),
                "spool_ready_workers": [
                    worker
                    for worker in workers
                    if worker in db2_worker_profile_runner.SPOOL_READY_WORKERS
                ],
                "not_spool_migrated": non_spool_by_profile[profile],
            }
            for profile, workers in db2_worker_profile_runner.PROFILE_WORKERS.items()
        },
        "worker_policy": {
            "spool_ready_workers": sorted(db2_worker_profile_runner.SPOOL_READY_WORKERS),
            "one_shot_allowed_workers": safe_spool_workers,
            "banned_workers": sorted(db2_worker_profile_runner.BANNED_WORKERS),
            "experimental_workers": sorted(db2_worker_profile_runner.EXPERIMENTAL_WORKERS),
        },
        "contract_policy": {
            "openclaw_role": "control_plane_only",
            "execution_plane": "docker_container_worker",
            "future_contracts_are_not_executable": True,
            "production_commands_exposed": False,
            "contract_show_template": "db2ctl contracts show CONTRACT_ID",
            "contract_verify_command": "db2ctl contracts verify-all",
        },
        "schedule_gate": {
            "full_profile_must_not_start_on_hold": True,
            "worker_specific_schedule_required": True,
            "container_mount_doctor_required_before_worker": True,
            "worker_specific_schedule_template": "db2ctl schedule --profile safe --only-worker WORKER",
            "worker_specific_up_template": "db2ctl up safe --worker WORKER",
            "worker_specific_up_limited_template": "db2ctl up safe --worker WORKER --limit N",
        },
        "recovery_gate": {
            "stale_running_reset_dry_run": "db2ctl recovery stale-running-reset --snapshot-path SNAPSHOT",
            "stale_running_reset_execute": "db2ctl recovery stale-running-reset --execute --snapshot-path SNAPSHOT --confirm reset-stale-running",
            "requires_snapshot_integrity_ok": True,
            "requires_active_worker_count_zero": True,
            "requires_fresh_running_count_zero": True,
            "requires_no_lock_holders": True,
        },
        "stop_gates": [
            "integrity_not_ok",
            "searxng_delta",
            "writer_backlog_present",
            "writer_failed_spool_present",
            "stale_running_requires_reset_before_worker_start",
            "sidecar_cache_missing_for_long_run",
            "full_profile_contains_non_spool_migrated_workers",
        ],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Machine-readable DB2 outlink OpenClaw policy")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parse_args(argv)
    print(json.dumps(build_policy(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
