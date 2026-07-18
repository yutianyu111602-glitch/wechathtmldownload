#!/usr/bin/env python3
"""Validate the authoritative weekly package used as an incremental base.

The production package is mutable runtime state.  It must live outside an
immutable source checkout, agree with its own manifest, and never be older in
item coverage than the package currently advertised by the public manifest.
This command performs local reads only; callers supply an online item count
when they require the anti-rollback comparison.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUNTIME_DATA_ROOT = Path(
    r"F:\DevData\HuaidjRuntime\state\weekly_activity_cloudrun\data"
)
SCHEMA_VERSION = "huaidj_weekly_authoritative_base_validation.v1"


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _is_within(path: Path, root: Path) -> bool:
    try:
        _resolved(path).relative_to(_resolved(root))
    except ValueError:
        return False
    return True


def resolve_runtime_paths(
    *,
    current_release: str = "",
    data_root: str = "",
    allow_repo_fallback: bool = False,
    repo_root: Path = REPO_ROOT,
) -> tuple[Path, Path, str]:
    """Resolve explicit/env/SSOT runtime paths with an optional dev fallback."""

    explicit_current = str(current_release or "").strip()
    explicit_data = str(data_root or "").strip()
    env_current = os.environ.get("HUAIDJ_CURRENT_RELEASE_DIR", "").strip()
    env_data = os.environ.get("HUAIDJ_CLOUDRUN_DATA_ROOT", "").strip()

    selected_current = explicit_current or env_current
    selected_data = explicit_data or env_data
    source = "explicit" if explicit_current or explicit_data else "environment" if env_current or env_data else "runtime_ssot_default"

    if selected_current and not selected_data:
        selected_data = str(Path(selected_current).parent)
    if not selected_data:
        selected_data = str(DEFAULT_RUNTIME_DATA_ROOT)
    if not selected_current:
        selected_current = str(Path(selected_data) / "current_release")

    resolved_current = _resolved(Path(selected_current))
    resolved_data = _resolved(Path(selected_data))
    if (
        allow_repo_fallback
        and source == "runtime_ssot_default"
        and not resolved_current.exists()
    ):
        resolved_data = _resolved(repo_root / "services" / "weekly_activity_cloudrun" / "data")
        resolved_current = resolved_data / "current_release"
        source = "repo_dev_fallback"
    return resolved_current, resolved_data, source


def _read_json(path: Path) -> tuple[Any | None, str]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), ""
    except FileNotFoundError:
        return None, "missing"
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"invalid_json:{type(exc).__name__}"


def validate_authoritative_base(
    *,
    api_dir: Path,
    data_root: Path,
    repo_root: Path,
    min_items: int,
    expected_online_item_count: int = 0,
    require_external_runtime: bool = False,
) -> dict[str, Any]:
    api_dir = _resolved(api_dir)
    data_root = _resolved(data_root)
    repo_root = _resolved(repo_root)
    failures: list[str] = []

    expected_current = data_root / "current_release"
    if api_dir != expected_current:
        failures.append("current_release_not_under_configured_data_root")
    if require_external_runtime:
        if _is_within(api_dir, repo_root):
            failures.append("current_release_inside_source_checkout")
        if _is_within(data_root, repo_root):
            failures.append("cloudrun_data_root_inside_source_checkout")

    manifest_path = api_dir / "manifest.json"
    current_path = api_dir / "current.json"
    manifest, manifest_error = _read_json(manifest_path)
    current, current_error = _read_json(current_path)
    if manifest_error:
        failures.append(f"manifest_{manifest_error}")
    if current_error:
        failures.append(f"current_{current_error}")

    manifest_count = 0
    current_count = 0
    current_declared_count = 0
    if isinstance(manifest, dict):
        try:
            manifest_count = int(manifest.get("item_count") or 0)
        except (TypeError, ValueError):
            failures.append("manifest_item_count_invalid")
    elif manifest is not None:
        failures.append("manifest_root_not_object")

    if isinstance(current, dict):
        items = current.get("items")
        if not isinstance(items, list):
            failures.append("current_items_not_list")
        else:
            current_count = len(items)
        try:
            current_declared_count = int(current.get("item_count") or 0)
        except (TypeError, ValueError):
            failures.append("current_item_count_invalid")
    elif current is not None:
        failures.append("current_root_not_object")

    if manifest_count <= 0:
        failures.append("manifest_item_count_not_positive")
    if current_count <= 0:
        failures.append("current_item_count_not_positive")
    if manifest_count and current_count and manifest_count != current_count:
        failures.append("manifest_current_item_count_mismatch")
    if current_declared_count and current_count and current_declared_count != current_count:
        failures.append("current_declared_item_count_mismatch")
    if current_count < max(1, int(min_items)):
        failures.append("base_item_count_below_required_floor")
    if expected_online_item_count > 0 and current_count < expected_online_item_count:
        failures.append("base_item_count_below_online_manifest")

    unique_failures = sorted(set(failures))
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": not unique_failures,
        "api_dir": str(api_dir),
        "data_root": str(data_root),
        "repo_root": str(repo_root),
        "require_external_runtime": bool(require_external_runtime),
        "manifest_item_count": manifest_count,
        "current_item_count": current_count,
        "current_declared_item_count": current_declared_count,
        "min_items": max(1, int(min_items)),
        "expected_online_item_count": max(0, int(expected_online_item_count)),
        "failures": unique_failures,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-dir", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--min-items", type=int, default=40)
    parser.add_argument("--expected-online-item-count", type=int, default=0)
    parser.add_argument("--require-external-runtime", action="store_true")
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = validate_authoritative_base(
        api_dir=args.api_dir,
        data_root=args.data_root,
        repo_root=args.repo_root,
        min_items=args.min_items,
        expected_online_item_count=args.expected_online_item_count,
        require_external_runtime=args.require_external_runtime,
    )
    if args.report:
        write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
