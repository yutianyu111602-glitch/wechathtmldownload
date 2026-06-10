#!/usr/bin/env python3
"""Decide whether the current production release path has a SQLite write target.

This is a report-only surface check. It scans bounded current code locations,
separates active code from archived experiments, and records whether a real
production SQLite write runner exists for the selected CloudRun + miniprogram
release path.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = Path("reports/production_sqlite_surface_decision_20260518")
SCHEMA_VERSION = "stage7_production_sqlite_surface_decision.v1"

DEFAULT_SCAN_ROOTS = [
    Path("scripts"),
    Path("../../services/weekly_activity_cloudrun/src"),
    Path("../../services/weekly_activity_cloudrun/scripts"),
    Path("../../apps/weekly_activity_miniprogram/app.js"),
    Path("../../apps/weekly_activity_miniprogram/pages"),
    Path("../../apps/weekly_activity_miniprogram/utils"),
]

EXCLUDE_DIRS = {"node_modules", "tmp", "data", "test-artifacts", "__pycache__", ".git", "reports"}
SCAN_SUFFIXES = {".py", ".js", ".mjs", ".ts", ".json", ".md"}
SQLITE_PATTERNS = [
    r"\bsqlite3\b",
    r"\bbetter-sqlite3\b",
    r"\bsqlite\b",
    r"production_sqlite",
    r"sqlite_write",
    r"\.sqlite\b",
    r"\.db\b",
]
WRITE_PATTERNS = [
    r"sqlite3\.connect",
    r"new\s+Database\s*\(",
    r"better-sqlite3",
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def normalize(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path.resolve()).replace("\\", "/")


def iter_files(scan_roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for raw in scan_roots:
        path = raw if raw.is_absolute() else ROOT / raw
        if path.is_file() and path.suffix in SCAN_SUFFIXES:
            files.append(path)
            continue
        if not path.exists() or not path.is_dir():
            continue
        for child in path.rglob("*"):
            if any(part in EXCLUDE_DIRS for part in child.parts):
                continue
            if child.is_file() and child.suffix in SCAN_SUFFIXES:
                files.append(child)
    return sorted(set(files), key=lambda item: normalize(item))


def classify_hit(path: Path, text: str) -> str:
    rel = normalize(path).casefold()
    lowered = text.casefold()
    if "/archive_old/" in f"/{rel}" or "\\archive_old\\" in rel:
        return "archived_experiment"
    if (
        "production_sqlite_write_executed" in lowered
        or "production_sqlite_write_allowed" in lowered
        or "sqlite_write_executed" in lowered
        or "sqlite_write" in lowered and "false" in lowered
    ):
        return "gate_or_safety_reference"
    if "mode=ro" in lowered or "read-only" in lowered or "report-only" in lowered:
        return "read_only_or_report_only"
    if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in WRITE_PATTERNS):
        return "active_sqlite_write_candidate"
    return "sqlite_reference"


def scan_sqlite_references(scan_roots: list[Path]) -> dict[str, Any]:
    files = iter_files(scan_roots)
    references: list[dict[str, Any]] = []
    scanned_count = 0
    for path in files:
        scanned_count += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        if not any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in SQLITE_PATTERNS):
            continue
        line_numbers = []
        for idx, line in enumerate(text.splitlines(), start=1):
            if any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in SQLITE_PATTERNS):
                line_numbers.append(idx)
        references.append(
            {
                "path": normalize(path),
                "classification": classify_hit(path, text),
                "line_numbers": line_numbers[:20],
                "line_count": len(line_numbers),
            }
        )
    by_class: dict[str, int] = {}
    for item in references:
        by_class[item["classification"]] = by_class.get(item["classification"], 0) + 1
    return {"scanned_files": scanned_count, "references": references, "by_classification": by_class}


def build_report(*, out_dir: Path, scan_roots: list[Path] | None = None) -> dict[str, Any]:
    roots = scan_roots or DEFAULT_SCAN_ROOTS
    scan = scan_sqlite_references(roots)
    active_candidates = [
        item for item in scan["references"] if item["classification"] == "active_sqlite_write_candidate"
    ]
    current_release_candidates = [
        item
        for item in active_candidates
        if "services/weekly_activity_cloudrun" in item["path"]
        or "apps/weekly_activity_miniprogram" in item["path"]
    ]

    decision = (
        "production_sqlite_runner_candidate_found_needs_design"
        if current_release_candidates
        else "production_sqlite_not_applicable_to_current_selected_release_path"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": decision,
        "selected_release_path": [
            "services/weekly_activity_cloudrun packaged JSON/API",
            "apps/weekly_activity_miniprogram developer-version upload",
        ],
        "scan_roots": [normalize(root if root.is_absolute() else ROOT / root) for root in roots],
        "scan": scan,
        "current_release_sqlite_write_candidates": current_release_candidates,
        "production_sqlite_execution_required_now": bool(current_release_candidates),
        "production_sqlite_write_executed": False,
        "conclusion": (
            "Current selected production lane has no SQLite-backed consumer target; production SQLite remains a gate label, not an executable surface."
            if not current_release_candidates
            else "A current release-path SQLite write candidate exists; build a dedicated rollback/smoke runner before executing it."
        ),
        "safety": {
            "report_only": True,
            "production_sqlite_write_executed": False,
            "cloud_deploy_executed": False,
            "miniprogram_upload_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
            "secret_value_read_or_printed": False,
        },
        "writes": "report_only_production_sqlite_surface_decision",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "production_sqlite_surface_decision.json", report)
    write_markdown(out_dir / "production_sqlite_surface_decision.md", report)
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Production SQLite Surface Decision",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- ok: `{report['ok']}`",
        f"- production_sqlite_execution_required_now: `{report['production_sqlite_execution_required_now']}`",
        f"- production_sqlite_write_executed: `{report['production_sqlite_write_executed']}`",
        "",
        "## Conclusion",
        "",
        report["conclusion"],
        "",
        "## Scan Summary",
        "",
        f"- scanned_files: `{report['scan']['scanned_files']}`",
    ]
    for key, value in sorted(report["scan"]["by_classification"].items()):
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Current Release Candidates", ""])
    if report["current_release_sqlite_write_candidates"]:
        for item in report["current_release_sqlite_write_candidates"]:
            lines.append(f"- `{item['path']}` classification=`{item['classification']}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(report["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_scan_roots(values: list[str] | None) -> list[Path] | None:
    if not values:
        return None
    return [Path(value) for value in values]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scan-root", action="append", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(out_dir=args.out_dir, scan_roots=parse_scan_roots(args.scan_root))
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "production_sqlite_execution_required_now": report["production_sqlite_execution_required_now"],
                "current_release_candidates": len(report["current_release_sqlite_write_candidates"]),
                "report": str(args.out_dir / "production_sqlite_surface_decision.json"),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
