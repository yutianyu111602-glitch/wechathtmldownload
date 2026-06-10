#!/usr/bin/env python3
"""Build S232D-3B7 DB3 relation identity repair packet.

This is a report-only packet for the current
``db3_same_normalized_name_multi_id`` blocker. It consumes the S217/S185
source-provider acquisition workbench and splits every group into a repair
lane. It does not write DB3, start Docker/workers, call providers/models,
project DB2, deploy, upload, or submit review.
"""
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

STORY_ID = "S232D-3B7"
SCHEMA_VERSION = "atlas_relation_identity_s232d3b7_repair_packet.v1"
DECISION = "atlas_relation_identity_s232d3b7_repair_packet_ready_report_only_no_write"

DEFAULT_S217_DIR = (
    REPORTS_ROOT / "atlas_relation_identity_source_provider_acquisition_s217_after_s216_full_20260602"
)
DEFAULT_WORKBENCH = DEFAULT_S217_DIR / "source_provider_acquisition_workbench_s185.jsonl"
DEFAULT_PROVIDER = DEFAULT_S217_DIR / "provider_crosscheck_rows_s185.jsonl"
DEFAULT_MANUAL = DEFAULT_S217_DIR / "manual_review_rows_s185.jsonl"
DEFAULT_EXTERNAL = DEFAULT_S217_DIR / "external_or_manual_acquisition_rows_s185.jsonl"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3b7_repair_packet_20260603"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_ATLAS_RELATION_IDENTITY_S232D3B7_REPAIR_PACKET_20260603.md"

RAW_URL_RE = re.compile(r"https?://", re.IGNORECASE)
PRIVATE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/mnt/[a-z]/|/home/pc/|\\\\)", re.IGNORECASE)
SECRET_RE = re.compile(
    r"(?:bearer\s+[a-z0-9._~+/=-]+|sk-[a-z0-9]{12,}|x-auth-key\s*[:=]|"
    r"cookie_value|token_value|password\s*[:=]|authorization\s*[:=]|sessionid=|api[_-]?key\s*[:=])",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
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


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def first(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            nested = first(*value)
            if nested:
                return nested
            continue
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def group_id(row: dict[str, Any]) -> str:
    return first(row.get("group_id"), (row.get("source_group_row") or {}).get("group_id"))


def identity_token(row: dict[str, Any]) -> str:
    source_group = row.get("source_group_row") if isinstance(row.get("source_group_row"), dict) else {}
    return first(source_group.get("identity_token"), row.get("unicode_compact_values"), group_id(row))


def route_for_group(
    row: dict[str, Any],
    provider_groups: set[str],
    manual_groups: set[str],
    external_groups: set[str],
) -> str:
    gid = group_id(row)
    if gid in provider_groups:
        return "provider_crosscheck_review"
    if gid in manual_groups:
        return "manual_disposition_review"
    if gid in external_groups:
        return "external_evidence_required"
    return "blocked_no_current_input"


def candidate_disposition(repair_lane: str) -> str:
    if repair_lane == "provider_crosscheck_review":
        return "merge_candidate"
    if repair_lane == "manual_disposition_review":
        return "needs_more_evidence"
    if repair_lane == "external_evidence_required":
        return "needs_more_evidence"
    return "needs_more_evidence"


def compact_common_evidence(row: dict[str, Any]) -> dict[str, Any]:
    common = row.get("common_evidence") if isinstance(row.get("common_evidence"), dict) else {}
    keys = [
        "common_cities",
        "common_event_titles",
        "common_source_accounts",
        "common_source_ref_ids",
        "common_source_titles",
        "common_venue_ids",
        "common_venue_names",
    ]
    return {key: as_list(common.get(key))[:8] for key in keys}


def missing_fields(row: dict[str, Any], repair_lane: str) -> list[str]:
    missing: list[str] = []
    source_group = row.get("source_group_row") if isinstance(row.get("source_group_row"), dict) else {}
    common = compact_common_evidence(row)
    if not any(common.get(key) for key in ("common_source_accounts", "common_source_ref_ids", "common_source_titles")):
        missing.append("source_anchor")
    if not any(common.get(key) for key in ("common_venue_ids", "common_venue_names", "common_event_titles")):
        missing.append("venue_or_event_anchor")
    if int(source_group.get("row_count") or len(as_list(row.get("dj_ids")))) != 2:
        missing.append("exactly_two_profiles")
    if as_list(source_group.get("s183_risk_reasons")):
        missing.append("risk_disposition")
    if repair_lane == "manual_disposition_review":
        missing.append("manual_disposition_approval")
    if repair_lane == "external_evidence_required":
        missing.append("external_source_provider_evidence")
    if repair_lane == "provider_crosscheck_review":
        missing.append("controller_source_backed_approval")
    if repair_lane == "blocked_no_current_input":
        missing.append("s217_route_input")
    return sorted(set(missing))


def stop_gates(repair_lane: str) -> list[str]:
    gates = [
        "report_only_packet",
        "approved_source_backed_disposition_missing",
        "s232d4_write_gate_not_released",
        "db_write_allowed_now_false",
    ]
    if repair_lane == "manual_disposition_review":
        gates.append("manual_review_required")
    if repair_lane == "external_evidence_required":
        gates.append("external_evidence_required")
    if repair_lane == "provider_crosscheck_review":
        gates.append("provider_crosscheck_review_required")
    if repair_lane == "blocked_no_current_input":
        gates.append("missing_s217_route_input")
    return gates


def build_repair_row(row: dict[str, Any], repair_lane: str, index: int) -> dict[str, Any]:
    source_group = row.get("source_group_row") if isinstance(row.get("source_group_row"), dict) else {}
    token = identity_token(row)
    common = compact_common_evidence(row)
    dj_ids = [str(item) for item in as_list(row.get("dj_ids"))]
    display_names = [str(item) for item in as_list(row.get("display_names"))]
    required_evidence = list(as_list(row.get("acceptance_requirements_before_write")))
    required_evidence.extend(["approved_source_backed_disposition", "explicit_s232d4_release"])
    return {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "work_order_id": f"s232d3b7:{index:04d}:{token or 'unknown'}",
        "group_id": group_id(row),
        "identity_token": token,
        "row_count": int(source_group.get("row_count") or len(dj_ids)),
        "dj_ids": dj_ids,
        "display_names": display_names,
        "s183_lane": first(row.get("s183_lane"), source_group.get("s183_lane")),
        "s185_route": first(row.get("s185_route")),
        "repair_lane": repair_lane,
        "candidate_disposition": candidate_disposition(repair_lane),
        "source_backed": repair_lane == "provider_crosscheck_review",
        "approved_for_s232d4": False,
        "required_evidence": sorted(set(str(item) for item in required_evidence if item)),
        "missing_fields": missing_fields(row, repair_lane),
        "stop_gates": stop_gates(repair_lane),
        "db_write_allowed_now": False,
        "db2_projection_allowed_now": False,
        "deploy_upload_release_allowed_now": False,
        "common_evidence": common,
    }


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


def build_packet(
    workbench_rows: list[dict[str, Any]],
    provider_rows: list[dict[str, Any]],
    manual_rows: list[dict[str, Any]],
    external_rows: list[dict[str, Any]],
    *,
    workbench_path: Path | None = None,
    provider_path: Path | None = None,
    manual_path: Path | None = None,
    external_path: Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    provider_groups = {group_id(row) for row in provider_rows if group_id(row)}
    manual_groups = {group_id(row) for row in manual_rows if group_id(row)}
    external_groups = {group_id(row) for row in external_rows if group_id(row)}

    repair_rows = [
        build_repair_row(row, route_for_group(row, provider_groups, manual_groups, external_groups), index)
        for index, row in enumerate(workbench_rows, start=1)
    ]
    lane_counts = Counter(row["repair_lane"] for row in repair_rows)
    disposition_counts = Counter(row["candidate_disposition"] for row in repair_rows)
    leak_findings = leak_scan(repair_rows)

    report = {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "generated_at": utc_now(),
        "decision": DECISION,
        "mode": "report_only_no_db_write_no_worker",
        "inputs": {
            "workbench_jsonl": str(workbench_path or ""),
            "provider_crosscheck_jsonl": str(provider_path or ""),
            "manual_review_jsonl": str(manual_path or ""),
            "external_or_manual_acquisition_jsonl": str(external_path or ""),
        },
        "counts": {
            "workbench_row_count": len(workbench_rows),
            "repair_row_count": len(repair_rows),
            "provider_crosscheck_input_count": len(provider_rows),
            "manual_review_input_count": len(manual_rows),
            "external_or_manual_acquisition_input_count": len(external_rows),
            "repair_lane_counts": dict(sorted(lane_counts.items())),
            "candidate_disposition_counts": dict(sorted(disposition_counts.items())),
            "source_backed_count": sum(1 for row in repair_rows if row["source_backed"]),
            "approved_for_s232d4_count": sum(1 for row in repair_rows if row["approved_for_s232d4"]),
            "db_write_allowed_now_count": sum(1 for row in repair_rows if row["db_write_allowed_now"]),
        },
        "s232d4_before_write_requirements": [
            "single_writer_lock",
            "db3_backup",
            "transaction_rollback",
            "no_empty_overwrite",
            "identity_redirect_preservation",
            "source_ref_preservation",
            "postwrite_readback",
            "rerun_relation_integrity_and_deploy_upload_preflight",
        ],
        "safety": {
            "report_only": True,
            "database_mutations": False,
            "db2_projection": False,
            "deploy_upload_review": False,
            "docker_or_worker_started": False,
            "network_fetch": False,
            "provider_or_model_call": False,
            "secret_read": False,
            "raw_url_private_path_secret_leak_count": len(leak_findings),
            "leak_findings": leak_findings,
        },
        "next_action": {
            "summary": "Review S232D-3B7 repair rows; only source-backed approved rows may later enter an explicit S232D-4 write gate.",
            "s232d4_allowed_now": False,
            "db_write_allowed_now": False,
        },
    }
    return report, repair_rows


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    counts = report["counts"]
    lane_counts = counts["repair_lane_counts"]
    lines = [
        "# S232D-3B7 DB3 Relation Identity Repair Packet",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Mode: `{report['mode']}`",
        f"- Workbench rows: `{counts['workbench_row_count']}`",
        f"- Repair rows: `{counts['repair_row_count']}`",
        f"- Provider-crosscheck ready: `{lane_counts.get('provider_crosscheck_review', 0)}`",
        f"- Manual review: `{lane_counts.get('manual_disposition_review', 0)}`",
        f"- External evidence required: `{lane_counts.get('external_evidence_required', 0)}`",
        f"- Blocked/no current input: `{lane_counts.get('blocked_no_current_input', 0)}`",
        f"- Approved for S232D-4 now: `{counts['approved_for_s232d4_count']}`",
        f"- DB write allowed rows now: `{counts['db_write_allowed_now_count']}`",
        f"- Leak findings: `{report['safety']['raw_url_private_path_secret_leak_count']}`",
        "",
        "## Boundary",
        "",
        "Report-only. No DB3 write, DB2 projection, Docker/worker start, network/provider/model call, deploy/upload/review/release, or credential read occurred.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build report-only S232D-3B7 DB3 relation identity repair packet.")
    parser.add_argument("--workbench", type=Path, default=DEFAULT_WORKBENCH)
    parser.add_argument("--provider-crosscheck", type=Path, default=DEFAULT_PROVIDER)
    parser.add_argument("--manual-review", type=Path, default=DEFAULT_MANUAL)
    parser.add_argument("--external-acquisition", type=Path, default=DEFAULT_EXTERNAL)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report, repair_rows = build_packet(
        read_jsonl(args.workbench),
        read_jsonl(args.provider_crosscheck),
        read_jsonl(args.manual_review),
        read_jsonl(args.external_acquisition),
        workbench_path=args.workbench,
        provider_path=args.provider_crosscheck,
        manual_path=args.manual_review,
        external_path=args.external_acquisition,
    )
    report_json = args.out_dir / "atlas_relation_identity_s232d3b7_repair_packet.json"
    rows_jsonl = args.out_dir / "s232d3b7_repair_rows.jsonl"
    write_json(report_json, report)
    write_jsonl(rows_jsonl, repair_rows)
    if not args.json_only:
        write_markdown(args.out_dir / "atlas_relation_identity_s232d3b7_repair_packet.md", report)
        write_markdown(args.scorecard, report)
    print(f"decision={report['decision']}")
    print(f"repair_row_count={report['counts']['repair_row_count']}")
    print(f"provider_crosscheck_review={report['counts']['repair_lane_counts'].get('provider_crosscheck_review', 0)}")
    print(f"manual_disposition_review={report['counts']['repair_lane_counts'].get('manual_disposition_review', 0)}")
    print(f"external_evidence_required={report['counts']['repair_lane_counts'].get('external_evidence_required', 0)}")
    print(f"approved_for_s232d4_count={report['counts']['approved_for_s232d4_count']}")
    print(f"db_write_allowed_now_count={report['counts']['db_write_allowed_now_count']}")
    print(f"json={display_path(report_json)}")
    return 0 if report["safety"]["raw_url_private_path_secret_leak_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
