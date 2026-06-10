#!/usr/bin/env python3
"""Repair relocatable weekly API manifest provenance fields.

This script only updates package-local manifest metadata. It does not touch
current items, posters, source maps, DBs, CloudBase, CloudRun, or mini-program
state.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "weekly_api_manifest_provenance_repair.v1"
SCRIPT_DIR = Path(__file__).resolve().parent
STAGE7_ROOT = SCRIPT_DIR.parent
REPO_ROOT = STAGE7_ROOT.parents[1]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_path_label(value: str | Path) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    path = Path(raw)
    try:
        resolved = path.resolve()
        try:
            return resolved.relative_to(REPO_ROOT).as_posix()
        except (OSError, ValueError):
            parts = list(resolved.parts)
            lowered = [part.lower() for part in parts]
            if "reports" in lowered:
                index = lowered.index("reports")
                return Path(*parts[index:]).as_posix()
    except OSError:
        pass
    return Path(raw.replace("\\", "/")).name or raw


def same_path(left: str, right: Path) -> bool:
    if not str(left or "").strip():
        return False
    try:
        return Path(left).resolve() == right.resolve()
    except OSError:
        return False


def build_repair(api_dir: Path, *, write: bool) -> dict[str, Any]:
    api_dir = api_dir.resolve()
    manifest_path = api_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest.json not found: {manifest_path}")

    manifest = read_json(manifest_path)
    generated_at = now_iso()
    changes: list[dict[str, Any]] = []

    desired_out_dir = str(api_dir)
    previous_out_dir = str(manifest.get("out_dir") or "").strip()
    if not same_path(previous_out_dir, api_dir):
        changes.append(
            {
                "field": "out_dir",
                "previous": safe_path_label(previous_out_dir),
                "next": safe_path_label(api_dir),
                "reason": "manifest_out_dir_must_match_current_api_dir_before_quality_gate",
            }
        )
        if write:
            manifest["out_dir"] = desired_out_dir

    if write and changes:
        manifest["manifest_provenance_repaired_at"] = generated_at
        write_json(manifest_path, manifest)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "api_dir": safe_path_label(api_dir),
        "manifest_path": safe_path_label(manifest_path),
        "write": bool(write),
        "changed_count": len(changes),
        "changes": changes,
        "ok": True,
        "boundary": {
            "report_only": not bool(write),
            "manifest_write_executed": bool(write and changes),
            "current_items_modified": False,
            "poster_fields_modified": False,
            "source_map_modified": False,
            "cloudbase_storage_write_executed": False,
            "cloudbase_db_write_executed": False,
            "db2_write_executed": False,
            "db3_write_executed": False,
            "cloudrun_deploy_executed": False,
            "miniprogram_upload_executed": False,
            "secret_read_executed": False,
        },
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    report = build_repair(args.api_dir, write=args.write)
    write_json(args.report, report)
    print(json.dumps({"ok": report["ok"], "changed_count": report["changed_count"], "report": safe_path_label(args.report)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
