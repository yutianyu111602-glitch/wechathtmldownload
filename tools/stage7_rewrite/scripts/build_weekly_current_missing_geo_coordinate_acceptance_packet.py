#!/usr/bin/env python3
"""Build a no-write coordinate acceptance packet for registry-backed rows.

This consumes the no-write registry acceptance packet and records which rows
are ready for a later explicit coordinate write gate. It does not write
coordinates, mutate registries, rebuild packages, call providers, or publish.
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

SCHEMA_VERSION = "weekly_current_missing_geo_coordinate_acceptance_packet.v1"
DECISION_READY = "weekly_current_missing_geo_coordinate_acceptance_ready_no_write"
DECISION_PARTIAL = "weekly_current_missing_geo_coordinate_acceptance_partial_no_write"
DECISION_BLOCKED = "weekly_current_missing_geo_coordinate_acceptance_blocked_no_write"
STORY_ID = "WEEKLY-CURRENT-MISSING-GEO-COORDINATE-ACCEPTANCE-20260603"

DEFAULT_REGISTRY_ACCEPTANCE_PACKET = (
    REPORTS_ROOT
    / "weekly_current_missing_geo_registry_acceptance_packet_20260603"
    / "weekly_current_missing_geo_registry_acceptance_packet.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_current_missing_geo_coordinate_acceptance_packet_20260603"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_CURRENT_MISSING_GEO_COORDINATE_ACCEPTANCE_PACKET_20260603.md"

RAW_LEAK_PATTERNS = [
    re.compile(r"https?://[^\s\"']+", re.I),
    re.compile(r"[A-Za-z]:\\Users\\pc\\", re.I),
    re.compile(r"/home/pc/", re.I),
    re.compile(r"\\\\wsl", re.I),
    re.compile(r"(cookie|token|secret|password|authorization)\s*[:=]\s*[^,\s\"'}]+", re.I),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def first(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, list):
            nested = first(*value)
            if nested:
                return nested
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def coordinate_checks(row: dict[str, Any]) -> dict[str, bool]:
    return {
        "registry_evidence_accepted": bool(row.get("accepted_registry_evidence_now")),
        "registry_preflight_ready": bool(row.get("coordinate_acceptance_preflight_ready_now")),
        "no_missing_registry_acceptance_checks": not row.get("missing_acceptance_checks"),
        "registry_venue_id_present": bool(first(row.get("registry_venue_id"))),
        "registry_address_present": bool(first(row.get("registry_address_full"))),
        "registry_city_present": bool(first(row.get("registry_city_name"))),
        "gcj02_coordinate_system": first(row.get("registry_geo_coord_system")).upper() == "GCJ-02",
        "coordinate_lng_present": is_number(row.get("registry_geo_lng")),
        "coordinate_lat_present": is_number(row.get("registry_geo_lat")),
        "registry_last_verified_at_present": bool(first(row.get("registry_last_verified_at"))),
        "source_url_hash_present": bool(first(row.get("source_url_hash"))),
        "source_account_hash_present": bool(first(row.get("source_account_hash"))),
    }


def missing_checks(checks: dict[str, bool]) -> list[str]:
    return [key for key, value in checks.items() if not value]


def build_coordinate_row(row: dict[str, Any], index: int) -> dict[str, Any]:
    checks = coordinate_checks(row)
    missing = missing_checks(checks)
    ready = not missing
    return {
        "schema_version": SCHEMA_VERSION,
        "row_id": f"coordinate_acceptance:{index:03d}:{first(row.get('current_item_id'), 'missing-id')}",
        "source_registry_acceptance_row_id": first(row.get("row_id")),
        "source_review_row_id": first(row.get("source_review_row_id")),
        "source_acceptance_row_id": first(row.get("source_acceptance_row_id")),
        "current_item_id": first(row.get("current_item_id")),
        "event_id": first(row.get("event_id")),
        "title": first(row.get("title")),
        "city": first(row.get("city")),
        "venue_name": first(row.get("venue_name")),
        "source_url_hash": first(row.get("source_url_hash")),
        "source_account_hash": first(row.get("source_account_hash")),
        "registry_venue_id": first(row.get("registry_venue_id")),
        "registry_canonical_name": first(row.get("registry_canonical_name")),
        "registry_city_name": first(row.get("registry_city_name")),
        "registry_address_full": first(row.get("registry_address_full")),
        "target_geo_lng": row.get("registry_geo_lng"),
        "target_geo_lat": row.get("registry_geo_lat"),
        "target_geo_coord_system": first(row.get("registry_geo_coord_system")),
        "target_geo_source": first(row.get("registry_geo_source")),
        "registry_last_verified_at": first(row.get("registry_last_verified_at")),
        "coordinate_acceptance_checks": checks,
        "missing_coordinate_acceptance_checks": missing,
        "coordinate_acceptance_status": "ready_for_explicit_coordinate_write_gate"
        if ready
        else "blocked_coordinate_acceptance_checks",
        "coordinate_acceptance_preflight_ready_now": ready,
        "explicit_coordinate_write_gate_released": False,
        "coordinate_write_allowed_now": False,
        "provider_or_geocode_call_allowed_now": False,
        "registry_mutation_allowed_now": False,
        "current_package_mutation_allowed_now": False,
        "db_write_allowed_now": False,
        "cloudbase_sync_allowed_now": False,
        "deploy_upload_review_release_allowed_now": False,
        "next_required_gate": "explicit_coordinate_write_gate_with_lock_backup_transaction_readback",
    }


def build_venue_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[first(row.get("registry_venue_id"), "missing_registry_venue_id")].append(row)

    out: list[dict[str, Any]] = []
    for venue_id, venue_rows in sorted(grouped.items()):
        first_row = venue_rows[0]
        ready_count = sum(1 for row in venue_rows if row["coordinate_acceptance_preflight_ready_now"])
        out.append(
            {
                "schema_version": SCHEMA_VERSION,
                "registry_venue_id": venue_id,
                "registry_canonical_name": first(first_row.get("registry_canonical_name")),
                "registry_city_name": first(first_row.get("registry_city_name")),
                "registry_address_full": first(first_row.get("registry_address_full")),
                "target_geo_lng": first_row.get("target_geo_lng"),
                "target_geo_lat": first_row.get("target_geo_lat"),
                "target_geo_coord_system": first(first_row.get("target_geo_coord_system")),
                "current_item_count": len(venue_rows),
                "coordinate_acceptance_preflight_ready_count": ready_count,
                "blocked_coordinate_acceptance_count": len(venue_rows) - ready_count,
                "explicit_coordinate_write_gate_released": False,
                "coordinate_write_allowed_now": False,
                "sample_current_item_ids": [row["current_item_id"] for row in venue_rows[:8]],
            }
        )
    return out


def find_raw_leaks(payload: Any) -> list[dict[str, Any]]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    findings: list[dict[str, Any]] = []
    for pattern in RAW_LEAK_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            findings.append({"pattern": pattern.pattern, "count": len(matches)})
    return findings


def build_packet_from_source(
    *,
    source_packet: dict[str, Any],
    registry_acceptance_packet_display_path: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source_rows = list(source_packet.get("acceptance_rows") or [])
    coordinate_rows = [build_coordinate_row(row, index) for index, row in enumerate(source_rows, start=1)]
    ready_rows = [row for row in coordinate_rows if row["coordinate_acceptance_preflight_ready_now"]]
    blocked_rows = [row for row in coordinate_rows if not row["coordinate_acceptance_preflight_ready_now"]]
    venue_groups = build_venue_groups(coordinate_rows)
    status_counts = Counter(row["coordinate_acceptance_status"] for row in coordinate_rows)
    city_counts = Counter(first(row.get("city")) or "unknown_city" for row in coordinate_rows)
    leak_findings = find_raw_leaks({"coordinate_rows": coordinate_rows, "venue_groups": venue_groups})
    summary = {
        "input_registry_acceptance_row_count": len(source_rows),
        "coordinate_acceptance_row_count": len(coordinate_rows),
        "coordinate_acceptance_preflight_ready_count": len(ready_rows),
        "blocked_coordinate_acceptance_count": len(blocked_rows),
        "unique_registry_venue_count": len(venue_groups),
        "explicit_coordinate_write_gate_released_count": 0,
        "coordinate_write_allowed_count": 0,
        "provider_or_geocode_call_allowed_count": 0,
        "registry_mutation_allowed_count": 0,
        "current_package_mutation_allowed_count": 0,
        "db_write_allowed_count": 0,
        "cloudbase_sync_allowed_count": 0,
        "deploy_upload_review_release_allowed_count": 0,
        "raw_url_output_count": 0,
        "raw_url_private_path_secret_leak_count": sum(finding["count"] for finding in leak_findings),
        "status_counts": dict(sorted(status_counts.items())),
        "top_city_counts": dict(city_counts.most_common(20)),
    }
    if ready_rows and not blocked_rows:
        decision = DECISION_READY
    elif ready_rows:
        decision = DECISION_PARTIAL
    else:
        decision = DECISION_BLOCKED
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "story_id": STORY_ID,
        "decision": decision,
        "mode": "report_only_coordinate_acceptance_preflight_no_write",
        "inputs": {
            "registry_acceptance_packet": registry_acceptance_packet_display_path,
            "registry_acceptance_decision": source_packet.get("decision"),
            "registry_acceptance_story_id": source_packet.get("story_id"),
        },
        "summary": summary,
        "coordinate_rows": coordinate_rows,
        "venue_groups": venue_groups,
        "leak_findings": leak_findings,
        "release_guard_notification_fields": [
            "story_id",
            "decision",
            "summary",
            "boundary",
            "next_required_gate",
        ],
        "next_required_gate": "explicit_coordinate_write_gate_with_lock_backup_transaction_no_empty_overwrite_readback",
        "boundary": {
            "report_only": True,
            "network_fetch_executed": False,
            "docker_worker_executed": False,
            "deepseek_or_model_calls": False,
            "provider_or_geocode_calls": False,
            "coordinate_acceptance_gate_released": False,
            "coordinate_write_executed": False,
            "database_mutation_executed": False,
            "registry_mutation_executed": False,
            "current_package_mutation_executed": False,
            "cloudbase_sync_executed": False,
            "cloudrun_deployed": False,
            "upload_executed": False,
            "review_submitted": False,
            "public_release_executed": False,
            "credential_or_secret_read": False,
            "browser_profile_read": False,
            "raw_source_url_output": False,
        },
    }
    return packet, coordinate_rows


def build_packet_from_source_for_test(source_packet: dict[str, Any]) -> dict[str, Any]:
    packet, _rows = build_packet_from_source(
        source_packet=source_packet,
        registry_acceptance_packet_display_path="test_registry_acceptance_packet.json",
    )
    return packet


def build_packet(repo_root: Path, registry_acceptance_packet_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    repo_root = repo_root.resolve()
    registry_acceptance_packet_path = (
        registry_acceptance_packet_path
        if registry_acceptance_packet_path.is_absolute()
        else repo_root / registry_acceptance_packet_path
    )
    return build_packet_from_source(
        source_packet=load_json(registry_acceptance_packet_path),
        registry_acceptance_packet_display_path=display_path(registry_acceptance_packet_path, repo_root),
    )


def render_markdown(packet: dict[str, Any]) -> str:
    summary = packet["summary"]
    lines = [
        "# Weekly Current Missing Geo Coordinate Acceptance Packet",
        "",
        f"Generated: {packet['generated_at']}",
        "",
        f"- story_id: `{packet['story_id']}`",
        f"- decision: `{packet['decision']}`",
        f"- registry acceptance packet: `{packet['inputs']['registry_acceptance_packet']}`",
        f"- coordinate acceptance rows: `{summary['coordinate_acceptance_row_count']}`",
        f"- preflight ready: `{summary['coordinate_acceptance_preflight_ready_count']}`",
        f"- blocked coordinate acceptance: `{summary['blocked_coordinate_acceptance_count']}`",
        f"- unique registry venues: `{summary['unique_registry_venue_count']}`",
        f"- explicit coordinate write gate released: `{summary['explicit_coordinate_write_gate_released_count']}`",
        f"- coordinate write allowed: `{summary['coordinate_write_allowed_count']}`",
        f"- DB write allowed: `{summary['db_write_allowed_count']}`",
        f"- leak findings: `{summary['raw_url_private_path_secret_leak_count']}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in summary["status_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Next Gate",
            "",
            f"`{packet['next_required_gate']}`",
            "",
            "## Sample Rows",
            "",
        ]
    )
    for row in packet["coordinate_rows"][:20]:
        lines.append(
            "- "
            f"`{row['current_item_id']}` "
            f"venue=`{row['registry_venue_id']}` "
            f"status=`{row['coordinate_acceptance_status']}`"
        )
    if len(packet["coordinate_rows"]) > 20:
        lines.append(f"- ... `{len(packet['coordinate_rows']) - 20}` more rows")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Report-only coordinate acceptance preflight artifact. No raw source URL output, network fetch, Docker worker, DeepSeek/model/provider/geocode call, coordinate acceptance gate release, coordinate write, DB/registry/current-package mutation, CloudBase sync, CloudRun deploy, upload, review, release, credential read, or browser profile read occurred.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(packet: dict[str, Any], rows: list[dict[str, Any]], out_dir: Path, scorecard: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_current_missing_geo_coordinate_acceptance_packet.json"
    md_path = out_dir / "weekly_current_missing_geo_coordinate_acceptance_packet.md"
    rows_path = out_dir / "weekly_current_missing_geo_coordinate_acceptance_rows.jsonl"
    ready_path = out_dir / "weekly_current_missing_geo_coordinate_acceptance_ready_rows.jsonl"
    blocked_path = out_dir / "weekly_current_missing_geo_coordinate_acceptance_blocked_rows.jsonl"
    groups_path = out_dir / "weekly_current_missing_geo_coordinate_acceptance_venue_groups.jsonl"
    write_json(json_path, packet)
    write_jsonl(rows_path, rows)
    write_jsonl(ready_path, [row for row in rows if row["coordinate_acceptance_preflight_ready_now"]])
    write_jsonl(blocked_path, [row for row in rows if not row["coordinate_acceptance_preflight_ready_now"]])
    write_jsonl(groups_path, packet["venue_groups"])
    markdown = render_markdown(packet)
    md_path.write_text(markdown, encoding="utf-8")
    scorecard.parent.mkdir(parents=True, exist_ok=True)
    scorecard.write_text(markdown, encoding="utf-8")
    return {
        "json": json_path,
        "markdown": md_path,
        "rows": rows_path,
        "ready_rows": ready_path,
        "blocked_rows": blocked_path,
        "venue_groups": groups_path,
        "scorecard": scorecard,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--registry-acceptance-packet", type=Path, default=DEFAULT_REGISTRY_ACCEPTANCE_PACKET)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    packet, rows = build_packet(repo_root, args.registry_acceptance_packet)
    paths = write_reports(packet, rows, args.out_dir, args.scorecard)
    print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "decision": packet["decision"],
                "summary": packet["summary"],
                "output_json": str(paths["json"]),
                "scorecard": str(paths["scorecard"]),
            },
            ensure_ascii=False,
        )
    )
    return 0 if packet["summary"]["raw_url_private_path_secret_leak_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
