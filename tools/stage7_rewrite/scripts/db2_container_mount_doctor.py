from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


DEFAULT_DB = Path(os.environ.get("DB2_SWARM_DB", "/db2-data/atlas_swarm_data.sqlite"))
DEFAULT_SCRIPTS_DIR = Path(os.environ.get("DB2_SCRIPTS_DIR", "/db2-scripts"))
DEFAULT_SPOOL = Path(os.environ.get("DB2_WRITE_SPOOL", "/db2-spool"))
DEFAULT_CACHE_DB = Path(os.environ.get("DB2_SIDECAR_CACHE_DB", "/db2-cache/db2_sidecar_cache.sqlite"))
DEFAULT_AVATAR_DIR = Path(os.environ.get("DB2_AVATAR_OUTPUT_DIR", "/db2-avatar-output"))


def path_status(path: Path) -> dict:
    return {
        "path": str(path),
        "exists": path.exists(),
        "is_file": path.is_file(),
        "is_dir": path.is_dir(),
        "size_bytes": path.stat().st_size if path.exists() and path.is_file() else 0,
    }


def inspect_mounts(
    *,
    db: Path = DEFAULT_DB,
    scripts_dir: Path = DEFAULT_SCRIPTS_DIR,
    spool_dir: Path = DEFAULT_SPOOL,
    cache_db: Path = DEFAULT_CACHE_DB,
    avatar_dir: Path = DEFAULT_AVATAR_DIR,
) -> dict:
    checks = {
        "live_db": path_status(db),
        "scripts_dir": path_status(scripts_dir),
        "avatar_worker": path_status(scripts_dir / "avatar_dl_worker.py"),
        "outlink_worker": path_status(scripts_dir / "outlink_expand_worker.py"),
        "spool_dir": path_status(spool_dir),
        "spool_incoming": path_status(spool_dir / "incoming"),
        "cache_db": path_status(cache_db),
        "avatar_output_dir": path_status(avatar_dir),
    }
    blockers: list[str] = []
    if not checks["live_db"]["is_file"] or checks["live_db"]["size_bytes"] <= 0:
        blockers.append("live_db_mount_missing_or_empty")
    if not checks["scripts_dir"]["is_dir"]:
        blockers.append("scripts_dir_mount_missing")
    if not checks["avatar_worker"]["is_file"]:
        blockers.append("avatar_worker_missing_in_container")
    if not checks["outlink_worker"]["is_file"]:
        blockers.append("outlink_worker_missing_in_container")
    if not checks["spool_dir"]["is_dir"]:
        blockers.append("spool_dir_mount_missing")
    if not checks["cache_db"]["is_file"]:
        blockers.append("sidecar_cache_mount_missing")
    if not checks["avatar_output_dir"]["is_dir"]:
        blockers.append("avatar_output_mount_missing")
    return {
        "doctor": "db2_container_mount_doctor",
        "checks": checks,
        "blockers": blockers,
        "passed": not blockers,
        "would_write": False,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only DB2 container mount doctor")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--scripts-dir", type=Path, default=DEFAULT_SCRIPTS_DIR)
    parser.add_argument("--spool-dir", type=Path, default=DEFAULT_SPOOL)
    parser.add_argument("--cache-db", type=Path, default=DEFAULT_CACHE_DB)
    parser.add_argument("--avatar-dir", type=Path, default=DEFAULT_AVATAR_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = inspect_mounts(
        db=args.db,
        scripts_dir=args.scripts_dir,
        spool_dir=args.spool_dir,
        cache_db=args.cache_db,
        avatar_dir=args.avatar_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
