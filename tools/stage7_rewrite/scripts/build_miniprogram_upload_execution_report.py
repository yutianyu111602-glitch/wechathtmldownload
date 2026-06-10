#!/usr/bin/env python3
"""Build a structured report from a WeChat miniprogram upload log.

The report records only upload evidence that is already present in a log. It
does not upload, submit review, read private-key contents, deploy CloudRun, or
call paid APIs.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_LOG = Path("reports/miniprogram_upload_20260518/upload_2026.05.18.1.log")
DEFAULT_OUT_DIR = Path("reports/miniprogram_upload_20260518")
DEFAULT_VERSION = "2026.05.18.1"
DEFAULT_DESC = "Stage7 atlas weekly-api-022 materialized LLM evidence"
DEFAULT_APPID = "wx0bc0a1d9d892af2d"
SCHEMA_VERSION = "stage7_miniprogram_upload_execution_report.v1"


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


def parse_upload_log(log_path: Path, *, version: str, desc: str, appid: str) -> dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    upload_status_done = '"message":"upload","status":"done"' in text or '"message": "upload", "status": "done"' in text
    final_done = "[log] done" in text
    request_seen = "https://servicewechat.com/wxa/ci/upload" in text
    version_seen = f"version={version}" in text or f"Version: {version}" in text
    desc_seen = desc in text or "desc=" in text
    appid_seen = appid in text
    zip_match = re.search(r"upload zip buffer size:\s+(\d+)", text)
    code_files_match = re.search(r"getCodeFiles: count:\s*(\d+)", text)
    compile_done_count = len(re.findall(r'"status":"done"', text))
    blockers: list[str] = []
    if not log_path.exists():
        blockers.append("upload_log_missing")
    if not request_seen:
        blockers.append("upload_request_not_seen")
    if not upload_status_done:
        blockers.append("upload_status_done_not_seen")
    if not final_done:
        blockers.append("final_done_not_seen")
    if not version_seen:
        blockers.append("version_not_seen")
    if not appid_seen:
        blockers.append("appid_not_seen")
    return {
        "blockers": blockers,
        "compile_done_count": compile_done_count,
        "code_file_count": int(code_files_match.group(1)) if code_files_match else None,
        "desc_seen": desc_seen,
        "final_done": final_done,
        "log_bytes": log_path.stat().st_size if log_path.exists() else 0,
        "log_path": str(log_path),
        "request_url_seen": request_seen,
        "upload_status_done": upload_status_done,
        "version_seen": version_seen,
        "zip_buffer_size": int(zip_match.group(1)) if zip_match else None,
    }


def build_report(
    *,
    log_path: Path,
    out_dir: Path,
    version: str,
    desc: str,
    appid: str,
) -> dict[str, Any]:
    parsed = parse_upload_log(log_path, version=version, desc=desc, appid=appid)
    blockers = parsed["blockers"]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": not blockers,
        "decision": "miniprogram_developer_version_upload_verified" if not blockers else "miniprogram_upload_evidence_blocked",
        "blockers": blockers,
        "appid": appid,
        "version": version,
        "desc": desc,
        "parsed_log": parsed,
        "limits": {
            "developer_version_uploaded": not blockers,
            "review_submitted": False,
            "production_release_completed": False,
            "mp_console_manual_review_still_required": True,
        },
        "safety": {
            "miniprogram_upload_executed": not blockers,
            "review_submit_executed": False,
            "cloud_deploy_executed_by_this_script": False,
            "production_sqlite_write_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
            "secret_value_read_or_printed": False,
            "private_key_content_read_by_this_report": False,
        },
        "writes": "miniprogram_developer_version_upload_evidence",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "miniprogram_upload_execution_report.json", report)
    write_markdown(out_dir / "miniprogram_upload_execution_report.md", report)
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Miniprogram Upload Execution Report",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- ok: `{report['ok']}`",
        f"- appid: `{report['appid']}`",
        f"- version: `{report['version']}`",
        f"- desc: `{report['desc']}`",
        "",
        "## Evidence",
        "",
        f"- log_path: `{report['parsed_log']['log_path']}`",
        f"- log_bytes: `{report['parsed_log']['log_bytes']}`",
        f"- request_url_seen: `{report['parsed_log']['request_url_seen']}`",
        f"- upload_status_done: `{report['parsed_log']['upload_status_done']}`",
        f"- final_done: `{report['parsed_log']['final_done']}`",
        f"- zip_buffer_size: `{report['parsed_log']['zip_buffer_size']}`",
        f"- code_file_count: `{report['parsed_log']['code_file_count']}`",
        "",
        "## Limits",
        "",
        "- This is a developer-version upload only.",
        "- It is not an mp.weixin.qq.com review submission.",
        "- It is not a completed public production release by itself.",
        "",
        "## Safety",
        "",
        "- This report parser does not read private-key contents and does not perform the upload itself.",
    ]
    if report["blockers"]:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- {item}" for item in report["blockers"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--desc", default=DEFAULT_DESC)
    parser.add_argument("--appid", default=DEFAULT_APPID)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        log_path=args.log,
        out_dir=args.out_dir,
        version=args.version,
        desc=args.desc,
        appid=args.appid,
    )
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "version": report["version"],
                "blockers": report["blockers"],
                "report": str(args.out_dir / "miniprogram_upload_execution_report.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
