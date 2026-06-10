#!/usr/bin/env python3
"""Build S232D-3B8 no-write candidate preflight from S232D-3B7 repair rows."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"

STORY_ID = "S232D-3B8"
SCHEMA_VERSION = "atlas_relation_identity_s232d3b8_candidate_preflight.v1"
DECISION = "atlas_relation_identity_s232d3b8_candidate_preflight_ready_report_only_no_write"

DEFAULT_REPAIR_PACKET = (
    REPORTS_ROOT
    / "atlas_relation_identity_s232d3b7_repair_packet_20260603"
    / "atlas_relation_identity_s232d3b7_repair_packet.json"
)
DEFAULT_REPAIR_ROWS = (
    REPORTS_ROOT
    / "atlas_relation_identity_s232d3b7_repair_packet_20260603"
    / "s232d3b7_repair_rows.jsonl"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3b8_candidate_preflight_20260603"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_ATLAS_RELATION_IDENTITY_S232D3B8_CANDIDATE_PREFLIGHT_20260603.md"

RAW_URL_RE = re.compile(r"https?://", re.IGNORECASE)
PRIVATE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/mnt/[a-z]/|/home/pc/|\\\\)", re.IGNORECASE)
SECRET_RE = re.compile(
    r"(?:bearer\s+[a-z0-9._~+/=-]+|sk-[a-z0-9]{12,}|x-auth-key\s*[:=]|"
    r"cookie_value|token_value|password\s*[:=]|authorization\s*[:=]|sessionid=|api[_-]?key\s*[:=])",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"Expected object JSONL row at {path}:{line_number}")
        rows.append(payload)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def leak_scan(payload: Any) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    def walk(value: Any, pointer: str) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                walk(nested, f"{pointer}.{key}" if pointer else str(key))
            return
        if isinstance(value, list):
            for idx, nested in enumerate(value):
                walk(nested, f"{pointer}[{idx}]")
            return
        if not isinstance(value, str):
            return
        for kind, pattern in (("raw_url", RAW_URL_RE), ("private_path", PRIVATE_PATH_RE), ("secret_like", SECRET_RE)):
            if pattern.search(value):
                findings.append({"kind": kind, "pointer": pointer})

    walk(payload, "")
    return findings


def approval_status(row: dict[str, Any]) -> str:
    if row.get("source_backed"):
        return "pending_source_backed_controller_approval"
    if row.get("repair_lane") == "manual_disposition_review":
        return "pending_manual_disposition_review"
    if row.get("repair_lane") == "external_evidence_required":
        return "pending_external_source_evidence"
    return "pending_route_repair"


def manual_review_required(row: dict[str, Any]) -> bool:
    return row.get("repair_lane") in {
        "manual_disposition_review",
        "external_evidence_required",
        "blocked_no_current_input",
    }


def build_candidate_row(index: int, row: dict[str, Any]) -> dict[str, Any]:
    repair_lane = str(row.get("repair_lane") or "")
    return {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "candidate_id": f"s232d3b8:{index:04d}:{str(row.get('identity_token') or row.get('group_id') or 'unknown')}",
        "source_work_order_id": str(row.get("work_order_id") or ""),
        "group_id": str(row.get("group_id") or ""),
        "dj_ids": [str(item) for item in row.get("dj_ids", [])],
        "display_names": [str(item) for item in row.get("display_names", [])],
        "evidence_lane": repair_lane,
        "missing_evidence": [str(item) for item in row.get("missing_fields", [])],
        "proposed_disposition": str(row.get("candidate_disposition") or "needs_more_evidence"),
        "approval_status": approval_status(row),
        "source_backed_candidate": bool(row.get("source_backed")),
        "source_backed_approval_required": True,
        "manual_review_required": manual_review_required(row),
        "external_evidence_required": repair_lane == "external_evidence_required",
        "merge_allowed_now": False,
        "db_write_allowed_now": False,
        "db2_projection_allowed_now": False,
        "deploy_upload_release_allowed_now": False,
        "s232d4_write_gate_released": False,
        "required_before_s232d4": [
            "approved_source_backed_disposition",
            "manual_or_controller_approval_artifact",
            "explicit_s232d4_write_gate",
            "single_writer_lock",
            "db3_backup",
            "transaction_rollback_plan",
            "source_ref_preservation",
            "postwrite_readback",
        ],
        "stop_gates": sorted(
            set(
                [str(item) for item in row.get("stop_gates", [])]
                + [
                    "s232d4_write_gate_not_released",
                    "merge_allowed_now_false",
                    "db_write_allowed_now_false",
                ]
            )
        ),
    }


def build_report(
    repo_root: Path,
    repair_packet_path: Path,
    repair_rows_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    repo_root = repo_root.resolve()
    repair_packet_path = repair_packet_path if repair_packet_path.is_absolute() else repo_root / repair_packet_path
    repair_rows_path = repair_rows_path if repair_rows_path.is_absolute() else repo_root / repair_rows_path
    repair_packet = load_json(repair_packet_path)
    repair_rows = read_jsonl(repair_rows_path)
    candidate_rows = [build_candidate_row(index, row) for index, row in enumerate(repair_rows, start=1)]
    lane_counts = Counter(row["evidence_lane"] for row in candidate_rows)
    approval_counts = Counter(row["approval_status"] for row in candidate_rows)
    disposition_counts = Counter(row["proposed_disposition"] for row in candidate_rows)
    leak_findings = leak_scan(candidate_rows)
    summary = {
        "input_repair_row_count": len(repair_rows),
        "candidate_row_count": len(candidate_rows),
        "source_backed_candidate_count": sum(1 for row in candidate_rows if row["source_backed_candidate"]),
        "manual_review_required_count": sum(1 for row in candidate_rows if row["manual_review_required"]),
        "external_evidence_required_count": sum(1 for row in candidate_rows if row["external_evidence_required"]),
        "approved_for_s232d4_count": 0,
        "merge_allowed_now_count": 0,
        "db_write_allowed_now_count": 0,
        "s232d4_write_gate_released_count": 0,
        "raw_url_private_path_secret_leak_count": len(leak_findings),
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "generated_at": utc_now(),
        "decision": DECISION,
        "mode": "report_only_candidate_preflight_no_db_write_no_worker",
        "inputs": {
            "s232d3b7_repair_packet": display_path(repair_packet_path, repo_root),
            "s232d3b7_repair_rows": display_path(repair_rows_path, repo_root),
            "s232d3b7_decision": str(repair_packet.get("decision") or ""),
        },
        "summary": summary,
        "evidence_lane_counts": dict(sorted(lane_counts.items())),
        "approval_status_counts": dict(sorted(approval_counts.items())),
        "proposed_disposition_counts": dict(sorted(disposition_counts.items())),
        "boundary": {
            "database_mutations": False,
            "db2_projection": False,
            "deploy_upload_review": False,
            "docker_or_worker_started": False,
            "network_fetch": False,
            "provider_or_model_call": False,
            "secret_read": False,
            "s232d4_write_gate_released": False,
        },
        "leak_findings": leak_findings,
        "next_required_gate": "manual_or_source_backed_approval_artifact_before_explicit_s232d4_write_gate",
        "consumer_notification_fields": [
            "decision",
            "summary",
            "evidence_lane_counts",
            "approval_status_counts",
            "boundary",
            "next_required_gate",
        ],
    }
    return report, candidate_rows


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    lanes = report["evidence_lane_counts"]
    lines = [
        "# S232D-3B8 DB3 Candidate Preflight",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Mode: `{report['mode']}`",
        f"- Candidate rows: `{summary['candidate_row_count']}`",
        f"- Source-backed candidates: `{summary['source_backed_candidate_count']}`",
        f"- Manual review required: `{summary['manual_review_required_count']}`",
        f"- External evidence required: `{summary['external_evidence_required_count']}`",
        f"- Provider-crosscheck lane: `{lanes.get('provider_crosscheck_review', 0)}`",
        f"- Manual disposition lane: `{lanes.get('manual_disposition_review', 0)}`",
        f"- External evidence lane: `{lanes.get('external_evidence_required', 0)}`",
        f"- Approved for S232D-4 now: `{summary['approved_for_s232d4_count']}`",
        f"- DB write allowed rows now: `{summary['db_write_allowed_now_count']}`",
        f"- Leak findings: `{summary['raw_url_private_path_secret_leak_count']}`",
        "",
        "## Boundary",
        "",
        "Report-only. No DB3 write, DB2 projection, Docker/worker start, network/provider/model call, deploy/upload/review/release, credential read, or S232D-4 release occurred.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build report-only S232D-3B8 candidate preflight.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--repair-packet", type=Path, default=DEFAULT_REPAIR_PACKET)
    parser.add_argument("--repair-rows", type=Path, default=DEFAULT_REPAIR_ROWS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    report, rows = build_report(repo_root, args.repair_packet, args.repair_rows)
    report_json = args.out_dir / "atlas_relation_identity_s232d3b8_candidate_preflight.json"
    rows_jsonl = args.out_dir / "s232d3b8_candidate_rows.jsonl"
    source_backed_jsonl = args.out_dir / "s232d3b8_source_backed_candidate_rows.jsonl"
    manual_jsonl = args.out_dir / "s232d3b8_manual_review_required_rows.jsonl"
    external_jsonl = args.out_dir / "s232d3b8_external_evidence_required_rows.jsonl"
    write_json(report_json, report)
    write_jsonl(rows_jsonl, rows)
    write_jsonl(source_backed_jsonl, [row for row in rows if row["source_backed_candidate"]])
    write_jsonl(manual_jsonl, [row for row in rows if row["manual_review_required"]])
    write_jsonl(external_jsonl, [row for row in rows if row["external_evidence_required"]])
    write_scorecard(args.out_dir / "atlas_relation_identity_s232d3b8_candidate_preflight.md", report)
    write_scorecard(args.scorecard, report)
    print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "decision": report["decision"],
                "summary": report["summary"],
                "output_json": str(report_json),
                "scorecard": str(args.scorecard),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["summary"]["raw_url_private_path_secret_leak_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
