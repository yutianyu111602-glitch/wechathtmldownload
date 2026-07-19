#!/usr/bin/env python3
"""Run the read-only Weekly deploy/upload preflight.

This is a local gate for the final CloudRun deploy / mini-program upload lane.
It deliberately does not deploy, upload, submit review, geocode, rebuild data,
call LLMs, or read private key material. Key-gated Clean-CI quality is skipped
unless the caller passes an explicit private-key path.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "weekly_deploy_upload_preflight_20260531"
DEFAULT_TIMEOUT_SECONDS = 180
MINIAPP_TEST_DIR = REPO_ROOT / "apps" / "weekly_activity_miniprogram" / "tests"
COORDINATE_FRESHNESS_SCRIPT = REPO_ROOT / "tools" / "stage7_rewrite" / "scripts" / "audit_weekly_coordinate_freshness_queue.py"


Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class CheckSpec:
    check_id: str
    title: str
    argv: tuple[str, ...]
    cwd: Path = REPO_ROOT
    required: bool = True
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    skip_reason: str = ""


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def tool_name(name: str) -> str:
    if os.name == "nt" and name in {"npm", "node", "powershell"}:
        return {"npm": "npm.cmd", "node": "node.exe", "powershell": "powershell.exe"}[name]
    return name


def redact_argv(argv: tuple[str, ...] | list[str]) -> list[str]:
    redacted: list[str] = []
    skip_next = False
    for part in argv:
        if skip_next:
            redacted.append("<private-key-path>")
            skip_next = False
            continue
        redacted.append(part)
        if part.lower() == "-privatekeypath":
            skip_next = True
    return redacted


def command_text(argv: tuple[str, ...] | list[str]) -> str:
    return " ".join(redact_argv(argv))


def validate_command_is_safe(spec: CheckSpec) -> None:
    lowered = [part.lower() for part in spec.argv]
    text = " ".join(lowered)
    first = Path(lowered[0]).name if lowered else ""

    if "direct_cloudbase_deploy.py" in text:
        raise ValueError(f"{spec.check_id}: direct CloudBase deploy is final-stage only")
    if "geocode_weekly_activity_places.py" in text:
        raise ValueError(f"{spec.check_id}: geocode/provider calls are not part of deploy/upload preflight")
    if "materialize_source_grounded_outputs.mjs" in text:
        raise ValueError(f"{spec.check_id}: release materialization/rebuild is not part of this preflight")
    if first in {"tcb", "tcb.cmd", "tcb.exe"}:
        raise ValueError(f"{spec.check_id}: tcb deploy commands are final-stage only")
    if "cloudrun" in lowered and "deploy" in lowered:
        raise ValueError(f"{spec.check_id}: cloudrun deploy command is final-stage only")
    if "bake_and_deploy.py" in text and "--dry-run" not in lowered and "--prepare-only" not in lowered:
        raise ValueError(f"{spec.check_id}: bake_and_deploy.py must use --dry-run or --prepare-only in preflight")
    if any(
        upload_script in text
        for upload_script in ("upload_native_windows.ps1", "upload_devtools_cli_windows.ps1")
    ) and "-whatif" not in lowered:
        raise ValueError(f"{spec.check_id}: mini-program upload must use -WhatIf in preflight")
    if any("submit" in part and "review" in part for part in lowered):
        raise ValueError(f"{spec.check_id}: review submission is not part of deploy/upload preflight")


def build_check_specs(
    out_dir: Path,
    *,
    relation_sample_limit: int = 500,
    atlas_db2_path: Path | None = None,
    atlas_db3_path: Path | None = None,
    weekly_current_path: Path | None = None,
    include_weekly_api: bool = True,
    include_miniapp: bool = True,
    include_coordinate_freshness: bool = True,
    clean_ci_private_key_path: Path | None = None,
) -> list[CheckSpec]:
    relation_out = out_dir / "atlas_relation_field_integrity"
    coordinate_out = out_dir / "coordinate_freshness_latest_claim"
    specs = []
    if include_coordinate_freshness:
        specs.append(
            CheckSpec(
                "coordinate_freshness_latest_claim",
                "Coordinate freshness latest-claim gate",
                (
                    sys.executable,
                    rel(COORDINATE_FRESHNESS_SCRIPT),
                    "--out-dir",
                    str(coordinate_out),
                ),
                timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            )
        )
    relation_argv = [
        sys.executable,
        "tools/stage7_rewrite/scripts/audit_atlas_relation_field_integrity.py",
        "--sample-limit",
        str(relation_sample_limit),
        "--out-dir",
        str(relation_out),
    ]
    if atlas_db2_path is not None:
        relation_argv.extend(("--db2", str(atlas_db2_path)))
    if atlas_db3_path is not None:
        relation_argv.extend(("--db3", str(atlas_db3_path)))
    if weekly_current_path is not None:
        relation_argv.extend(("--weekly-current", str(weekly_current_path)))
    specs.append(
        CheckSpec(
            "atlas_relation_field_integrity",
            "DB2/DB3 relation field integrity guard",
            tuple(relation_argv),
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        )
    )
    if include_weekly_api:
        specs.append(
            CheckSpec(
                "weekly_api_tests",
                "CloudRun weekly-api Node test suite",
                (tool_name("npm"), "run", "weekly-api:test"),
                timeout_seconds=240,
            )
        )
    if include_miniapp:
        for test_file in sorted(MINIAPP_TEST_DIR.glob("*.test.cjs")):
            test_path = rel(test_file)
            specs.append(
                CheckSpec(
                    f"miniapp_{Path(test_path).stem.replace('-', '_')}",
                    f"Mini-program static test {Path(test_path).name}",
                    (tool_name("node"), test_path),
                    timeout_seconds=120,
                )
            )
    if clean_ci_private_key_path:
        specs.append(
            CheckSpec(
                "miniapp_clean_ci_quality",
                "Mini-program Clean-CI quality gate",
                (
                    tool_name("powershell"),
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    "apps/weekly_activity_miniprogram/scripts/Test-CleanCiQuality.ps1",
                    "-PrivateKeyPath",
                    str(clean_ci_private_key_path),
                ),
                timeout_seconds=240,
            )
        )
    else:
        specs.append(
            CheckSpec(
                "miniapp_clean_ci_quality",
                "Mini-program Clean-CI quality gate",
                tuple(),
                required=False,
                skip_reason="requires explicit --clean-ci-private-key-path; no key discovery or secret read is performed by this preflight",
            )
        )
    for spec in specs:
        if spec.argv:
            validate_command_is_safe(spec)
    return specs


def tail_text(value: str, limit: int = 3000) -> str:
    if len(value) <= limit:
        return value
    return value[-limit:]


def execute_spec(spec: CheckSpec, *, runner: Runner = subprocess.run, plan_only: bool = False) -> dict[str, Any]:
    base = {
        "check_id": spec.check_id,
        "title": spec.title,
        "required": spec.required,
        "cwd": rel(spec.cwd),
        "command": command_text(spec.argv) if spec.argv else "",
    }
    if spec.skip_reason:
        return {**base, "status": "skipped", "skip_reason": spec.skip_reason}
    if plan_only:
        return {**base, "status": "planned"}
    try:
        completed = runner(
            list(spec.argv),
            cwd=str(spec.cwd),
            timeout=spec.timeout_seconds,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        return {**base, "status": "failed", "returncode": 127, "stderr_tail": str(exc), "stdout_tail": ""}
    except subprocess.TimeoutExpired as exc:
        return {
            **base,
            "status": "failed",
            "returncode": 124,
            "stderr_tail": tail_text(str(exc.stderr or exc)),
            "stdout_tail": tail_text(str(exc.stdout or "")),
        }
    status = "passed" if completed.returncode == 0 else "failed"
    return {
        **base,
        "status": status,
        "returncode": completed.returncode,
        "stdout_tail": tail_text(completed.stdout or ""),
        "stderr_tail": tail_text(completed.stderr or ""),
    }


def summarize_results(results: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(results),
        "passed": sum(1 for item in results if item["status"] == "passed"),
        "failed": sum(1 for item in results if item["status"] == "failed"),
        "skipped": sum(1 for item in results if item["status"] == "skipped"),
        "planned": sum(1 for item in results if item["status"] == "planned"),
        "required_failed": sum(1 for item in results if item["status"] == "failed" and item.get("required", True)),
    }


def build_report(specs: list[CheckSpec], results: list[dict[str, Any]], out_dir: Path, *, plan_only: bool) -> dict[str, Any]:
    summary = summarize_results(results)
    if plan_only:
        decision = "weekly_deploy_upload_preflight_plan_ready"
    elif summary["required_failed"]:
        decision = "weekly_deploy_upload_preflight_findings"
    elif any(item["check_id"] == "miniapp_clean_ci_quality" and item["status"] == "skipped" for item in results):
        decision = "weekly_deploy_upload_preflight_local_passed_key_gate_not_run"
    else:
        decision = "weekly_deploy_upload_preflight_passed"
    return {
        "schema_version": "weekly_deploy_upload_preflight.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "decision": decision,
        "summary": summary,
        "out_dir": rel(out_dir),
        "checks": results,
        "command_plan": [
            {
                "check_id": spec.check_id,
                "required": spec.required,
                "command": command_text(spec.argv) if spec.argv else "",
                "skip_reason": spec.skip_reason,
            }
            for spec in specs
        ],
        "safety": {
            "report_only": True,
            "deployment_executed": False,
            "upload_executed": False,
            "review_submitted": False,
            "database_mutations": False,
            "coordinate_writes": False,
            "map_provider_calls": False,
            "model_calls_performed": False,
            "secret_files_read": False,
            "audio_video_cached_or_proxied": False,
        },
        "boundaries": [
            "Coordinate freshness is a required latest-claim gate; if it is not safe, deploy/upload must stay blocked.",
            "Relation guard is read-only against DB2/DB3 and writes reports only.",
            "CloudRun deployment commands are excluded from this preflight.",
            "Mini-program upload and WeChat review submission commands are excluded from this preflight.",
            "Clean-CI private key lookup is not automatic; pass an explicit path to run that optional gate.",
            "Geocode/provider calls, release rebuilds, DB writes, graph/vector writes, and LLM calls are excluded.",
        ],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Weekly Deploy Upload Preflight",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Total checks: `{report['summary']['total']}`",
        f"- Passed: `{report['summary']['passed']}`",
        f"- Failed: `{report['summary']['failed']}`",
        f"- Skipped: `{report['summary']['skipped']}`",
        f"- Planned: `{report['summary']['planned']}`",
        "",
        "## Checks",
        "",
    ]
    for item in report["checks"]:
        lines.append(f"- `{item['status']}` `{item['check_id']}`: {item['title']}")
        if item.get("skip_reason"):
            lines.append(f"  - skip: {item['skip_reason']}")
        if item.get("returncode") not in (None, 0):
            lines.append(f"  - returncode: `{item['returncode']}`")
    lines.extend(["", "## Command Plan", ""])
    for item in report["command_plan"]:
        marker = "required" if item["required"] else "optional"
        command = item["command"] or item.get("skip_reason", "")
        lines.append(f"- `{marker}` `{item['check_id']}`: `{command}`")
    lines.extend(["", "## Safety Boundary", ""])
    for key, value in report["safety"].items():
        lines.append(f"- `{key}`: `{str(value).lower()}`")
    lines.extend(["", "## Rules", ""])
    for rule in report["boundaries"]:
        lines.append(f"- {rule}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run_preflight(
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    relation_sample_limit: int = 500,
    atlas_db2_path: Path | None = None,
    atlas_db3_path: Path | None = None,
    weekly_current_path: Path | None = None,
    include_weekly_api: bool = True,
    include_miniapp: bool = True,
    include_coordinate_freshness: bool = True,
    clean_ci_private_key_path: Path | None = None,
    plan_only: bool = False,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    specs = build_check_specs(
        out_dir,
        relation_sample_limit=relation_sample_limit,
        atlas_db2_path=atlas_db2_path,
        atlas_db3_path=atlas_db3_path,
        weekly_current_path=weekly_current_path,
        include_weekly_api=include_weekly_api,
        include_miniapp=include_miniapp,
        include_coordinate_freshness=include_coordinate_freshness,
        clean_ci_private_key_path=clean_ci_private_key_path,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    results = [execute_spec(spec, runner=runner, plan_only=plan_only) for spec in specs]
    report = build_report(specs, results, out_dir, plan_only=plan_only)
    write_json(out_dir / "weekly_deploy_upload_preflight.json", report)
    write_markdown(out_dir / "weekly_deploy_upload_preflight.md", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run read-only Weekly deploy/upload preflight")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--relation-sample-limit", type=int, default=500)
    parser.add_argument("--atlas-db2", type=Path)
    parser.add_argument("--atlas-db3", type=Path)
    parser.add_argument("--weekly-current", type=Path)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--skip-coordinate-freshness", action="store_true")
    parser.add_argument("--skip-weekly-api", action="store_true")
    parser.add_argument("--skip-miniapp", action="store_true")
    parser.add_argument("--clean-ci-private-key-path", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_preflight(
        out_dir=args.out_dir,
        relation_sample_limit=args.relation_sample_limit,
        atlas_db2_path=args.atlas_db2,
        atlas_db3_path=args.atlas_db3,
        weekly_current_path=args.weekly_current,
        include_weekly_api=not args.skip_weekly_api,
        include_miniapp=not args.skip_miniapp,
        include_coordinate_freshness=not args.skip_coordinate_freshness,
        clean_ci_private_key_path=args.clean_ci_private_key_path,
        plan_only=args.plan_only,
    )
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "summary": report["summary"],
                "json": str(args.out_dir / "weekly_deploy_upload_preflight.json"),
                "markdown": str(args.out_dir / "weekly_deploy_upload_preflight.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 2 if report["summary"]["required_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
