#!/usr/bin/env python3
"""Build the miniprogram review/public-release boundary packet.

The packet verifies what the local miniprogram-ci installation can do after a
developer-version upload. It does not submit review, publish a public release,
read private-key contents, or call paid/external APIs.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_UPLOAD_REPORT = Path("reports/miniprogram_upload_20260518/miniprogram_upload_execution_report.json")
DEFAULT_PACKAGE_ROOT = Path("../../apps/weekly_activity_miniprogram/node_modules/miniprogram-ci")
DEFAULT_OUT_DIR = Path("reports/miniprogram_review_submission_boundary_20260518")
SCHEMA_VERSION = "stage7_miniprogram_review_submission_boundary.v1"

REVIEW_COMMAND_PATTERNS = [
    r"\bsubmitAudit\b",
    r"\bsubmit-audit\b",
    r"\bauditSubmit\b",
    r"\bpublicRelease\b",
    r"\bpublishRelease\b",
    r"\bpublic-release\b",
    r"\bpublish-release\b",
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def read_text(path: Path, max_chars: int = 4_000_000) -> str:
    if not path.exists():
        return ""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return handle.read(max_chars)


def package_version(package_root: Path) -> str:
    package_json = package_root / "package.json"
    if not package_json.exists():
        return ""
    try:
        return str(read_json(package_json).get("version") or "")
    except (OSError, json.JSONDecodeError):
        return ""


def extract_cli_commands(cli_text: str) -> list[str]:
    commands = set()
    for match in re.finditer(r"command\s*:\s*['\"]([^'\"]+)['\"]", cli_text):
        command = match.group(1).strip()
        if command and "<" not in command and "$0" not in command:
            commands.add(command)
    return sorted(commands)


def inspect_miniprogram_ci(package_root: Path) -> dict[str, Any]:
    readme = read_text(package_root / "README.md")
    cli = read_text(package_root / "dist" / "cli" / "index.js")
    combined = f"{readme}\n{cli}"
    cli_commands = extract_cli_commands(cli)
    review_pattern_hits = [
        pattern for pattern in REVIEW_COMMAND_PATTERNS if re.search(pattern, combined, flags=re.IGNORECASE)
    ]
    has_upload = "upload" in cli_commands or "#upload" in readme
    has_preview = "preview" in cli_commands or "#preview" in readme
    has_submit_review = any(
        re.search(pattern, combined, flags=re.IGNORECASE)
        for pattern in REVIEW_COMMAND_PATTERNS[:3]
    )
    has_public_release = bool(
        {"release", "public-release", "publish-release"} & set(cli_commands)
    ) or any(re.search(pattern, combined, flags=re.IGNORECASE) for pattern in REVIEW_COMMAND_PATTERNS[3:])
    return {
        "package_root": str(package_root),
        "package_root_exists": package_root.exists(),
        "version": package_version(package_root),
        "readme_exists": (package_root / "README.md").exists(),
        "cli_index_exists": (package_root / "dist" / "cli" / "index.js").exists(),
        "cli_commands": cli_commands,
        "has_upload_command": bool(has_upload),
        "has_preview_command": bool(has_preview),
        "has_submit_review_command": bool(has_submit_review),
        "has_public_release_command": bool(has_public_release),
        "review_pattern_hits": review_pattern_hits,
    }


def build_report(*, upload_report_path: Path, package_root: Path, out_dir: Path) -> dict[str, Any]:
    upload_report = read_json(upload_report_path)
    ci = inspect_miniprogram_ci(package_root)
    developer_upload_verified = bool(upload_report.get("ok")) and bool(
        (upload_report.get("limits") or {}).get("developer_version_uploaded")
    )
    review_supported = bool(ci["has_submit_review_command"] or ci["has_public_release_command"])

    blockers = []
    if not developer_upload_verified:
        blockers.append("developer_version_upload_not_verified")
    if not ci["package_root_exists"]:
        blockers.append("miniprogram_ci_package_missing")
    if not ci["has_upload_command"]:
        blockers.append("miniprogram_ci_upload_command_not_found")
    if review_supported:
        blockers.append("local_runner_review_command_needs_dedicated_executor_before_use")

    decision = (
        "miniprogram_review_submission_manual_boundary_ready"
        if developer_upload_verified and ci["package_root_exists"] and not review_supported
        else "miniprogram_review_submission_boundary_blocked"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": decision == "miniprogram_review_submission_manual_boundary_ready",
        "decision": decision,
        "blockers": blockers,
        "upload_report_path": str(upload_report_path),
        "developer_version": {
            "uploaded": developer_upload_verified,
            "version": upload_report.get("version"),
            "appid": upload_report.get("appid"),
            "desc": upload_report.get("desc"),
        },
        "local_runner": ci,
        "limits": {
            "developer_version_uploaded": developer_upload_verified,
            "review_submission_supported_by_current_local_runner": review_supported,
            "review_submitted": False,
            "public_release_completed": False,
            "mp_console_manual_review_required": not review_supported,
        },
        "required_external_action": (
            "submit the verified developer version for review in mp.weixin.qq.com, then publish after approval"
            if not review_supported
            else "build a dedicated audited executor for the discovered review/release command before claiming completion"
        ),
        "safety": {
            "report_only": True,
            "miniprogram_upload_executed_by_this_script": False,
            "review_submit_executed": False,
            "public_release_executed": False,
            "cloud_deploy_executed": False,
            "production_sqlite_write_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "secret_value_read_or_printed": False,
            "private_key_content_read": False,
            "d_scan_executed": False,
        },
        "writes": "report_only_miniprogram_review_boundary",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "miniprogram_review_submission_boundary.json", report)
    write_markdown(out_dir / "miniprogram_review_submission_boundary.md", report)
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    runner = report["local_runner"]
    lines = [
        "# Miniprogram Review Submission Boundary",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- ok: `{report['ok']}`",
        f"- developer_version_uploaded: `{report['developer_version']['uploaded']}`",
        f"- version: `{report['developer_version']['version']}`",
        f"- miniprogram_ci_version: `{runner['version']}`",
        "",
        "## Local Runner Capability",
        "",
        f"- has_upload_command: `{runner['has_upload_command']}`",
        f"- has_preview_command: `{runner['has_preview_command']}`",
        f"- has_submit_review_command: `{runner['has_submit_review_command']}`",
        f"- has_public_release_command: `{runner['has_public_release_command']}`",
        f"- cli_commands: `{', '.join(runner['cli_commands'])}`",
        "",
        "## Boundary",
        "",
        "- The existing local runner proves developer-version upload only.",
        "- Review submission and public release are not claimed by this packet.",
        f"- required_external_action: `{report['required_external_action']}`",
        "",
        "## Safety",
        "",
    ]
    for key, value in sorted(report["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    if report["blockers"]:
        lines.extend(["", "## Blockers", ""])
        for blocker in report["blockers"]:
            lines.append(f"- {blocker}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upload-report", type=Path, default=DEFAULT_UPLOAD_REPORT)
    parser.add_argument("--package-root", type=Path, default=DEFAULT_PACKAGE_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        upload_report_path=args.upload_report,
        package_root=args.package_root,
        out_dir=args.out_dir,
    )
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "review_submitted": report["limits"]["review_submitted"],
                "manual_review_required": report["limits"]["mp_console_manual_review_required"],
                "report": str(args.out_dir / "miniprogram_review_submission_boundary.json"),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
