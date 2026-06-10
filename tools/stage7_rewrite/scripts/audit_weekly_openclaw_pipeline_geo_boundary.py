#!/usr/bin/env python3
"""Audit weekly OpenClaw pipeline scripts for the venue DB geo boundary.

Report-only. This does not call map APIs, read credentials, mutate release
packages, deploy CloudRun, or upload the mini-program. It only scans shell
script text for operational lines that would reintroduce geocoding, venue
anchor patching, or zero-geo blocking into the weekly release path.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_openclaw_pipeline_geo_boundary_audit_20260531"
)
DEFAULT_LIVE_SCRIPTS = [
    Path(r"\\wsl.localhost\Ubuntu\home\pc\scripts\huaidj-weekly-openclaw-stable.sh"),
    Path(r"\\wsl.localhost\Ubuntu\home\pc\scripts\huaidj-weekly-pipeline.sh"),
]

FORBIDDEN_OPERATIONAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "apply_venue_anchors": re.compile(r"\bapply_venue_anchors\.py\b"),
    "anchor_patch": re.compile(r"\banchor_patch\s*\("),
    "zero_geo_count": re.compile(r"\bzero_geo_count\b"),
    "geocode_runner": re.compile(r"\b(?:geocode_weekly_activity_places|apply_weekly_geocodes_to_api_package)\.py\b"),
    "map_api_geo_key": re.compile(r"\b(?:TENCENT_MAP_KEY|AMAP_KEY|AMAP_SECRET|LBS_SK)\b"),
}


def is_comment_or_blank(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def audit_script(path: Path) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "line_count": 0,
            "findings": [
                {
                    "path": str(path),
                    "line_number": 0,
                    "code": "script_missing",
                    "line": "",
                }
            ],
        }

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    for line_number, line in enumerate(lines, start=1):
        if is_comment_or_blank(line):
            continue
        for code, pattern in FORBIDDEN_OPERATIONAL_PATTERNS.items():
            if pattern.search(line):
                findings.append(
                    {
                        "path": str(path),
                        "line_number": line_number,
                        "code": code,
                        "line": line.strip(),
                    }
                )

    return {
        "path": str(path),
        "exists": True,
        "line_count": len(lines),
        "findings": findings,
    }


def audit_scripts(paths: list[Path]) -> dict[str, Any]:
    checked = [audit_script(path) for path in paths]
    findings = [finding for item in checked for finding in item["findings"]]
    decision = (
        "weekly_openclaw_pipeline_geo_boundary_passed"
        if not findings
        else "weekly_openclaw_pipeline_geo_boundary_failed"
    )
    return {
        "schema_version": "weekly_openclaw_pipeline_geo_boundary_audit.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "decision": decision,
        "script_count": len(paths),
        "checked_scripts": checked,
        "finding_count": len(findings),
        "findings": findings,
        "boundary": {
            "venue_address_coordinate_source": "fixed_venue_database",
            "forbidden_operational_steps": sorted(FORBIDDEN_OPERATIONAL_PATTERNS),
            "allows_comment_mentions": True,
            "map_api_calls_performed": False,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Weekly OpenClaw Pipeline Geo Boundary Audit",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Script count: `{report['script_count']}`",
        f"- Finding count: `{report['finding_count']}`",
        "- Boundary: venue addresses and coordinates are fixed venue DB data; weekly release scripts must not run geocode/anchor patch/zero-geo gates.",
        "- Map API calls performed: `false`",
        "",
        "## Checked Scripts",
        "",
    ]
    for item in report["checked_scripts"]:
        lines.append(f"- `{item['path']}`: exists=`{str(item['exists']).lower()}`, lines=`{item['line_count']}`")

    lines.extend(["", "## Findings", ""])
    if not report["findings"]:
        lines.append("No forbidden operational geo/anchor steps were found.")
    else:
        for finding in report["findings"]:
            lines.append(
                f"- `{finding['code']}` at `{finding['path']}:{finding['line_number']}`: `{finding['line']}`"
            )

    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This audit is report-only. It does not deploy CloudRun, upload a mini-program, rebuild a release, read credentials, call Tencent/Amap/MiMo/DeepSeek APIs, write source/raw DBs, or mutate graph/vector stores.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(report: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_openclaw_pipeline_geo_boundary_audit.json"
    md_path = out_dir / "weekly_openclaw_pipeline_geo_boundary_audit.md"
    write_json(json_path, report)
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--script",
        dest="scripts",
        action="append",
        default=[],
        help="Shell script path to audit. Repeat for multiple scripts. Defaults to the live WSL OpenClaw weekly scripts.",
    )
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--json-only", action="store_true", help="Print compact JSON to stdout instead of a human summary.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    scripts = [Path(value) for value in args.scripts] if args.scripts else DEFAULT_LIVE_SCRIPTS
    report = audit_scripts(scripts)
    paths = write_reports(report, args.report_dir)
    if args.json_only:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "decision": report["decision"],
                    "finding_count": report["finding_count"],
                    "report_json": str(paths["json"]),
                    "report_markdown": str(paths["markdown"]),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0 if report["finding_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
