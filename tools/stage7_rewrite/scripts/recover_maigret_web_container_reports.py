#!/usr/bin/env python3
"""Recover Maigret web reports from the local container report directory.

The Maigret web UI can finish the command and write /tmp/maigret_reports files
while the status page keeps showing "Search in progress". This script recovers
those local report files and writes candidate-only normalized evidence. It does
not write graph/vector/DB stores and it never inspects container environment.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from run_maigret_http_canary import parse_report_payload, reject_d_path, summarize_report, write_json, write_text


DEFAULT_SUMMARY = Path("reports/graph_maigret_canary_47k_plus_paid_20260518/maigret_canary_summary.json")
DEFAULT_OUT_DIR = Path("reports/graph_maigret_canary_47k_plus_paid_20260518")
DEFAULT_CONTAINER = "maigret-web-15051"
RUN_ID_RE = re.compile(r"(?:^|/)(\d{8}_\d{6})(?:$|/)")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def extract_run_id(status_path: str) -> str:
    match = RUN_ID_RE.search(status_path.strip())
    if not match:
        raise ValueError(f"cannot derive Maigret run id from status_path={status_path!r}")
    return match.group(1)


def username_from_report_path(path: Path) -> str:
    name = path.name
    if not name.startswith("report_") or path.suffix.lower() != ".json":
        raise ValueError(f"not a Maigret JSON report path: {path}")
    return name[len("report_") : -len(".json")]


def copy_container_reports(container: str, run_id: str, out_dir: Path) -> Path:
    reject_d_path(out_dir, "out_dir")
    local_dir = out_dir / f"container_reports_{run_id}"
    local_dir.mkdir(parents=True, exist_ok=True)
    container_dir = f"/tmp/maigret_reports/search_{run_id}/."
    completed = subprocess.run(
        ["docker", "cp", f"{container}:{container_dir}", str(local_dir)],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"docker cp failed for {container_dir}: {completed.stderr.strip()}")
    return local_dir


def summarize_reports(report_dir: Path) -> list[dict[str, Any]]:
    reject_d_path(report_dir, "report_dir")
    summaries: list[dict[str, Any]] = []
    for report_path in sorted(report_dir.glob("report_*.json")):
        username = username_from_report_path(report_path)
        try:
            payload = parse_report_payload(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            summaries.append(
                {
                    "username": username,
                    "found_count": 0,
                    "found": [],
                    "report_path": str(report_path),
                    "parse_error": str(exc),
                }
            )
            continue
        summary = summarize_report(username, payload)
        summary["report_path"] = str(report_path)
        summaries.append(summary)
    return summaries


def write_normalized_evidence(out_path: Path, summaries: list[dict[str, Any]], source_summary: dict[str, Any]) -> int:
    reject_d_path(out_path, "out_path")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    run_status_path = source_summary.get("status_path")
    for summary in summaries:
        for found in summary.get("found", []):
            rows.append(
                {
                    "schema_version": "stage7_external_evidence_candidate.v1",
                    "source": "maigret",
                    "source_status_path": run_status_path,
                    "username": summary.get("username"),
                    "site_name": found.get("site_name"),
                    "url": found.get("url"),
                    "tags": found.get("tags") or [],
                    "status": found.get("status"),
                    "confidence_cap": "candidate_only_not_identity_proof",
                    "review_status": "needs_source_backed_identity_review",
                    "graph_write_allowed": False,
                    "report_path": summary.get("report_path"),
                }
            )
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    tmp.replace(out_path)
    return len(rows)


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Maigret Web Container Report Recovery",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- decision: `{report['decision']}`",
        f"- container: `{report['container']}`",
        f"- run_id: `{report['run_id']}`",
        f"- json_reports: `{report['json_reports']}`",
        f"- normalized_evidence_rows: `{report['normalized_evidence_rows']}`",
        "",
        "## Found Counts",
        "",
    ]
    for item in report["summaries"]:
        lines.append(f"- `{item['username']}`: found_count=`{item['found_count']}`, report=`{item['report_path']}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Reports only.",
            "- Copied report files from the local Maigret container report directory.",
            "- Did not inspect container environment variables.",
            "- Maigret hit is not identity proof.",
            "- No graph/vector/DB write.",
            "- No paid API.",
            "- No D: scan.",
            "- No publish.",
        ]
    )
    write_text(path, "\n".join(lines) + "\n")


def recover(summary_path: Path, out_dir: Path, container: str) -> dict[str, Any]:
    reject_d_path(summary_path, "summary_path")
    reject_d_path(out_dir, "out_dir")
    source_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    run_id = extract_run_id(str(source_summary.get("status_path") or ""))
    report_dir = copy_container_reports(container, run_id, out_dir)
    summaries = summarize_reports(report_dir)
    normalized_path = out_dir / "maigret_normalized_candidate_evidence.jsonl"
    normalized_rows = write_normalized_evidence(normalized_path, summaries, source_summary)
    report = {
        "schema_version": "stage7_maigret_web_container_recovery.v1",
        "generated_at": now_iso(),
        "ok": bool(summaries),
        "decision": "maigret_canary_recovered_from_container_reports" if summaries else "maigret_canary_recovery_empty",
        "container": container,
        "run_id": run_id,
        "source_summary": str(summary_path),
        "report_dir": str(report_dir),
        "json_reports": len(summaries),
        "normalized_evidence_path": str(normalized_path),
        "normalized_evidence_rows": normalized_rows,
        "summaries": summaries,
        "writes": "reports_only",
        "warning": "Maigret hits are breadth evidence only and require source-backed identity review before graph use.",
        "safety": {
            "container_env_inspected": False,
            "cookie_or_token_exported": False,
            "d_scan_executed": False,
            "graph_write_executed": False,
            "model_call_executed": False,
            "paid_api_used": False,
            "qdrant_write_executed": False,
            "report_only": True,
        },
    }
    write_json(out_dir / "maigret_canary_recovered_summary.json", report)
    write_markdown(out_dir / "maigret_canary_recovered_summary.md", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = recover(args.summary, args.out_dir, args.container)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "json_reports": report["json_reports"],
                "normalized_evidence_rows": report["normalized_evidence_rows"],
                "summary": str(args.out_dir / "maigret_canary_recovered_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
