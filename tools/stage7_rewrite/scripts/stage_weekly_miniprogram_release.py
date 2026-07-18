#!/usr/bin/env python3
"""Stage a verified mini-program static API release.

The script creates an auditable upload plan with hashes. It does not call
CloudBase or read deployment credentials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "weekly_activity_miniprogram_release_stage.v1"
DEFAULT_REMOTE_ROOT = "weekly/releases"
JSON_NAMES = {"current.json", "manifest.json"}
JSON_DIRS = {"by-city", "by-date", "by-id", "source_actions"}


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_release_id(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in value.strip())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned or datetime.now().strftime("%Y%m%d-%H%M%S")


def iter_api_files(api_dir: Path) -> list[Path]:
    files: list[Path] = []
    for name in JSON_NAMES:
        path = api_dir / name
        if path.is_file():
            files.append(path)
    for dirname in JSON_DIRS:
        root = api_dir / dirname
        if root.is_dir():
            files.extend(path for path in root.rglob("*.json") if path.is_file())
    return sorted(files, key=lambda path: path.relative_to(api_dir).as_posix())


def validate_api_dir(api_dir: Path) -> dict[str, Any]:
    manifest = read_json(api_dir / "manifest.json")
    current = read_json(api_dir / "current.json")
    issues: list[str] = []
    if manifest.get("schema_version") != "weekly_activity_miniprogram_api.v1":
        issues.append("manifest_schema_version_invalid")
    if current.get("schema_version") != "weekly_activity_miniprogram_current.v1":
        issues.append("current_schema_version_invalid")
    if int(manifest.get("item_count") or -1) != int(current.get("item_count") or -2):
        issues.append("manifest_current_item_count_mismatch")
    if int(current.get("item_count") or 0) <= 0:
        issues.append("current_item_count_empty")
    return {"manifest": manifest, "current": current, "issues": issues}


def stage_release(*, api_dir: Path, out_dir: Path, release_id: str, remote_root: str) -> dict[str, Any]:
    validation = validate_api_dir(api_dir)
    if validation["issues"]:
        raise ValueError(", ".join(validation["issues"]))

    out_dir.mkdir(parents=True, exist_ok=True)
    files = iter_api_files(api_dir)
    staged_files: list[dict[str, Any]] = []
    remote_prefix = f"{remote_root.strip('/')}/{release_id}".strip("/")
    for source in files:
        relative = source.relative_to(api_dir)
        target = out_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        staged_files.append(
            {
                "path": relative.as_posix(),
                "local_path": str(target),
                "remote_path": f"{remote_prefix}/{relative.as_posix()}",
                "bytes": target.stat().st_size,
                "sha256": sha256_file(target),
            }
        )

    generated_at = datetime.now().isoformat(timespec="seconds")
    release_manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "api_dir": str(api_dir),
        "out_dir": str(out_dir),
        "release_id": release_id,
        "remote_prefix": remote_prefix,
        "item_count": validation["manifest"].get("item_count"),
        "city_route_count": validation["manifest"].get("city_route_count"),
        "date_route_count": validation["manifest"].get("date_route_count"),
        "file_count": len(staged_files),
        "files": staged_files,
    }
    write_json(out_dir / "release_manifest.json", release_manifest)
    write_json(
        out_dir / "cloudbase_upload_plan.json",
        {
            "schema_version": "weekly_activity_cloudbase_upload_plan.v1",
            "generated_at": generated_at,
            "release_id": release_id,
            "remote_prefix": remote_prefix,
            "upload_after_verification": True,
            "move_current_pointer_after_upload": True,
            "rollback_keep_previous_release": True,
            "files": staged_files,
        },
    )
    return release_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage weekly mini-program API files and write an upload plan")
    parser.add_argument("--api-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--release-id", default="")
    parser.add_argument("--remote-root", default=DEFAULT_REMOTE_ROOT)
    args = parser.parse_args(argv)

    api_dir = Path(args.api_dir)
    manifest = read_json(api_dir / "manifest.json")
    release_id = safe_release_id(args.release_id or str(manifest.get("generated_at") or ""))
    result = stage_release(
        api_dir=api_dir,
        out_dir=Path(args.out_dir),
        release_id=release_id,
        remote_root=args.remote_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
