#!/usr/bin/env python3
"""Build a no-write registry review packet for current missing-geo rows.

This packet consumes the registry-review slice from the evidence-acceptance
queue. It classifies rows that are ready for manual registry acceptance review
without approving, writing, provider-verifying, or mutating anything.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"

SCHEMA_VERSION = "weekly_current_missing_geo_registry_review_packet.v1"
DEFAULT_REGISTRY_REVIEW_ROWS = (
    REPORTS_ROOT
    / "weekly_current_missing_geo_evidence_acceptance_packet_20260603"
    / "weekly_current_missing_geo_registry_review_acceptance_rows.jsonl"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_current_missing_geo_registry_review_packet_20260603"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_CURRENT_MISSING_GEO_REGISTRY_REVIEW_PACKET_20260603.md"

PRIVATE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/mnt/[a-z]/|/home/pc/|\\\\)", re.IGNORECASE)
SECRET_RE = re.compile(
    r"(?:bearer\s+[a-z0-9._~+/=-]+|sk-[a-z0-9]{12,}|x-auth-key\s*[:=]|"
    r"cookie_value|token_value|password\s*[:=]|authorization\s*[:=]|sessionid=|api[_-]?key\s*[:=])",
    re.IGNORECASE,
)


def now_local() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        value = json.loads(text)
        if isinstance(value, dict):
            value["_input_path"] = display_path(path)
            value["_input_line"] = line_number
            rows.append(value)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, payload: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in payload)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
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


def required_review_checks(row: dict[str, Any]) -> dict[str, bool]:
    return {
        "source_url_present": bool(first(row.get("source_url"))),
        "source_account_present": bool(first(row.get("source_account_name"))),
        "current_city_matches_registry_city": first(row.get("city")) == first(row.get("registry_city_name")),
        "registry_venue_id_present": bool(first(row.get("registry_venue_id"))),
        "registry_address_present": bool(first(row.get("registry_address_full"))),
        "registry_gcj02_geo_present": bool(
            row.get("registry_geo_lng")
            and row.get("registry_geo_lat")
            and first(row.get("registry_geo_coord_system")).upper() == "GCJ-02"
        ),
        "registry_last_verified_at_present": bool(first(row.get("registry_last_verified_at"))),
        "registry_source_note_present": bool(first(row.get("registry_source_note"))),
        "local_evidence_status_expected": first(row.get("local_evidence_status"))
        == "venue_registry_address_geo_available_needs_review",
        "acceptance_lane_expected": first(row.get("acceptance_lane")) == "registry_review",
    }


def missing_checks(checks: dict[str, bool]) -> list[str]:
    return [key for key, value in checks.items() if not value]


def build_review_row(row: dict[str, Any], index: int) -> dict[str, Any]:
    checks = required_review_checks(row)
    missing = missing_checks(checks)
    ready = not missing
    return {
        "schema_version": SCHEMA_VERSION,
        "row_id": f"registry_review:{index:03d}:{first(row.get('current_item_id'), 'missing-id')}",
        "source_acceptance_row_id": first(row.get("row_id")),
        "current_item_id": first(row.get("current_item_id")),
        "event_id": first(row.get("event_id")),
        "title": first(row.get("title")),
        "city": first(row.get("city")),
        "venue_name": first(row.get("venue_name")),
        "source_url": first(row.get("source_url")),
        "source_account_name": first(row.get("source_account_name")),
        "registry_venue_id": first(row.get("registry_venue_id")),
        "registry_canonical_name": first(row.get("registry_canonical_name")),
        "registry_city_name": first(row.get("registry_city_name")),
        "registry_address_full": first(row.get("registry_address_full")),
        "registry_geo_lng": row.get("registry_geo_lng"),
        "registry_geo_lat": row.get("registry_geo_lat"),
        "registry_geo_coord_system": first(row.get("registry_geo_coord_system")),
        "registry_geo_source": first(row.get("registry_geo_source")),
        "registry_last_verified_at": first(row.get("registry_last_verified_at")),
        "registry_source_note": first(row.get("registry_source_note")),
        "review_checks": checks,
        "missing_review_checks": missing,
        "review_status": "ready_for_manual_registry_acceptance" if ready else "blocked_missing_registry_review_fields",
        "required_manual_review_actions": [
            "confirm_current_event_city_matches_registry_city",
            "confirm_source_url_or_account_anchor_matches_current_item",
            "confirm_registry_address_and_gcj02_coordinate_still_represent_same_venue",
            "record_reviewer_identity_or_review_artifact_before_acceptance",
            "keep_current_package_registry_db_and_coordinate_writes_disabled",
        ],
        "manual_reviewer_approved_now": False,
        "coordinate_acceptance_ready_now": False,
        "coordinate_write_allowed_now": False,
        "provider_or_geocode_call_allowed_now": False,
        "registry_mutation_allowed_now": False,
        "current_package_mutation_allowed_now": False,
    }


def build_venue_groups(review_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in review_rows:
        grouped[first(row.get("registry_venue_id"), "missing_registry_venue_id")].append(row)

    out: list[dict[str, Any]] = []
    for venue_id, rows in sorted(grouped.items()):
        first_row = rows[0]
        out.append(
            {
                "schema_version": SCHEMA_VERSION,
                "registry_venue_id": venue_id,
                "registry_canonical_name": first(first_row.get("registry_canonical_name")),
                "registry_city_name": first(first_row.get("registry_city_name")),
                "registry_address_full": first(first_row.get("registry_address_full")),
                "current_item_count": len(rows),
                "ready_for_manual_registry_acceptance_count": sum(
                    1 for row in rows if row["review_status"] == "ready_for_manual_registry_acceptance"
                ),
                "blocked_missing_review_fields_count": sum(
                    1 for row in rows if row["review_status"] == "blocked_missing_registry_review_fields"
                ),
                "sample_current_item_ids": [row["current_item_id"] for row in rows[:8]],
                "coordinate_write_allowed_now": False,
            }
        )
    return out


def leak_findings(payload: Any) -> list[dict[str, Any]]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    findings: list[dict[str, Any]] = []
    for label, pattern in (("private_path", PRIVATE_PATH_RE), ("secret_like", SECRET_RE)):
        matches = pattern.findall(text)
        if matches:
            findings.append({"type": label, "count": len(matches)})
    return findings


def build_packet(*, registry_review_rows: list[dict[str, Any]], registry_review_rows_path: Path) -> dict[str, Any]:
    review_rows = [build_review_row(row, index) for index, row in enumerate(registry_review_rows, start=1)]
    venue_groups = build_venue_groups(review_rows)
    status_counts = Counter(first(row.get("review_status")) for row in review_rows)
    city_counts = Counter(first(row.get("city")) or "unknown_city" for row in review_rows)
    ready_count = status_counts.get("ready_for_manual_registry_acceptance", 0)
    blocked_count = status_counts.get("blocked_missing_registry_review_fields", 0)
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_local(),
        "decision": "weekly_current_missing_geo_registry_review_packet_ready_for_manual_review_report_only"
        if ready_count and not blocked_count
        else "weekly_current_missing_geo_registry_review_packet_partial_report_only"
        if ready_count
        else "weekly_current_missing_geo_registry_review_packet_blocked_report_only",
        "inputs": {
            "registry_review_rows": display_path(registry_review_rows_path),
        },
        "summary": {
            "registry_review_input_count": len(registry_review_rows),
            "review_row_count": len(review_rows),
            "ready_for_manual_registry_acceptance_count": ready_count,
            "blocked_missing_review_fields_count": blocked_count,
            "manual_reviewer_approved_count": 0,
            "coordinate_acceptance_ready_count": 0,
            "coordinate_write_allowed_count": 0,
            "provider_or_geocode_call_allowed_count": 0,
            "unique_registry_venue_count": len(venue_groups),
            "status_counts": dict(sorted(status_counts.items())),
            "top_city_counts": dict(city_counts.most_common(20)),
        },
        "blocking_reasons": [
            "manual_registry_acceptance_not_recorded",
            "coordinate_acceptance_gate_not_released",
            "coordinate_write_gate_not_released",
        ],
        "next_action": {
            "first_gate": "manual_review_59_registry_rows_against_current_event_city_source_anchor_and_registry_source_note",
            "second_gate": "emit_reviewer_approval_artifact_for_accepted_rows_or_reject_rows_back_to_source_fetch",
            "third_gate": "run_provider_or_coordinate_acceptance_packet_after_manual_review",
            "fourth_gate": "explicit_coordinate_write_gate_with_lock_backup_transaction_no_empty_overwrite_readback",
        },
        "review_rows": review_rows,
        "venue_groups": venue_groups,
        "leak_findings": leak_findings({"review_rows": review_rows, "venue_groups": venue_groups}),
        "safety": {
            "report_only": True,
            "manual_reviewer_approval_recorded": False,
            "provider_or_geocode_call": False,
            "coordinate_acceptance": False,
            "coordinate_write": False,
            "registry_mutation": False,
            "current_package_mutation": False,
            "db_graph_vector_write": False,
            "docker_or_worker_started": False,
            "openclaw_pipeline_run": False,
            "deploy_upload_review": False,
            "model_call": False,
            "secret_read": False,
            "broad_disk_scan": False,
        },
    }
    return packet


def render_markdown(packet: dict[str, Any]) -> str:
    summary = packet["summary"]
    lines = [
        "# Weekly Current Missing Geo Registry Review Packet",
        "",
        f"- decision: `{packet['decision']}`",
        f"- registry_review_rows: `{packet['inputs']['registry_review_rows']}`",
        f"- review_row_count: `{summary['review_row_count']}`",
        f"- ready_for_manual_registry_acceptance_count: `{summary['ready_for_manual_registry_acceptance_count']}`",
        f"- blocked_missing_review_fields_count: `{summary['blocked_missing_review_fields_count']}`",
        f"- unique_registry_venue_count: `{summary['unique_registry_venue_count']}`",
        f"- manual_reviewer_approved_count: `{summary['manual_reviewer_approved_count']}`",
        f"- coordinate_acceptance_ready_count: `{summary['coordinate_acceptance_ready_count']}`",
        f"- coordinate_write_allowed_count: `{summary['coordinate_write_allowed_count']}`",
        f"- leak_findings: `{len(packet['leak_findings'])}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in summary["status_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Next Gates",
            "",
            f"1. `{packet['next_action']['first_gate']}`",
            f"2. `{packet['next_action']['second_gate']}`",
            f"3. `{packet['next_action']['third_gate']}`",
            f"4. `{packet['next_action']['fourth_gate']}`",
            "",
            "## Sample Rows",
            "",
        ]
    )
    for row in packet["review_rows"][:20]:
        lines.append(
            "- "
            f"`{row['current_item_id']}` "
            f"venue=`{row['registry_venue_id']}` "
            f"status=`{row['review_status']}`"
        )
    if len(packet["review_rows"]) > 20:
        lines.append(f"- ... `{len(packet['review_rows']) - 20}` more rows")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Report-only. No reviewer approval, provider/geocode call, coordinate acceptance, coordinate write, registry/current-release/DB mutation, Docker/worker/OpenClaw run, deploy/upload/review, model call, secret read, or broad disk scan occurred.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(packet: dict[str, Any], out_dir: Path, scorecard_path: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_current_missing_geo_registry_review_packet.json"
    md_path = out_dir / "weekly_current_missing_geo_registry_review_packet.md"
    rows_path = out_dir / "weekly_current_missing_geo_registry_review_rows.jsonl"
    ready_rows_path = out_dir / "weekly_current_missing_geo_registry_review_ready_rows.jsonl"
    blocked_rows_path = out_dir / "weekly_current_missing_geo_registry_review_blocked_rows.jsonl"
    groups_path = out_dir / "weekly_current_missing_geo_registry_review_venue_groups.jsonl"
    write_json(json_path, packet)
    md_text = render_markdown(packet)
    md_path.write_text(md_text, encoding="utf-8")
    scorecard_path.parent.mkdir(parents=True, exist_ok=True)
    scorecard_path.write_text(md_text, encoding="utf-8")
    rows_out = packet["review_rows"]
    write_jsonl(rows_path, rows_out)
    write_jsonl(ready_rows_path, [row for row in rows_out if row["review_status"] == "ready_for_manual_registry_acceptance"])
    write_jsonl(blocked_rows_path, [row for row in rows_out if row["review_status"] == "blocked_missing_registry_review_fields"])
    write_jsonl(groups_path, packet["venue_groups"])
    return {
        "json": json_path,
        "markdown": md_path,
        "rows": rows_path,
        "ready_rows": ready_rows_path,
        "blocked_rows": blocked_rows_path,
        "venue_groups": groups_path,
        "scorecard": scorecard_path,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-review-rows", type=Path, default=DEFAULT_REGISTRY_REVIEW_ROWS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packet = build_packet(
        registry_review_rows=read_jsonl(args.registry_review_rows),
        registry_review_rows_path=args.registry_review_rows,
    )
    paths = write_reports(packet, args.out_dir, args.scorecard)
    if args.json_only:
        print(json.dumps(packet, ensure_ascii=False, sort_keys=True))
    else:
        summary = packet["summary"]
        print(f"decision={packet['decision']}")
        print(f"review_row_count={summary['review_row_count']}")
        print(f"ready_for_manual_registry_acceptance_count={summary['ready_for_manual_registry_acceptance_count']}")
        print(f"blocked_missing_review_fields_count={summary['blocked_missing_review_fields_count']}")
        print(f"unique_registry_venue_count={summary['unique_registry_venue_count']}")
        print(f"coordinate_write_allowed_count={summary['coordinate_write_allowed_count']}")
        print(f"json={paths['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
