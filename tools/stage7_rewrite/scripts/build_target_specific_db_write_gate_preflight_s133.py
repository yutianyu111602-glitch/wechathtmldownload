#!/usr/bin/env python3
"""Build the S133 target-specific write-gate preflight packet.

Report-only. This turns the generic S132 SQLite lock/readback/rollback contract
into concrete target selectors for the coordinate blocker lane. It does not
write DB1/DB2/DB3, release JSON, venue registry JSON, or call map providers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "target_specific_db_write_gate_preflight_s133.v1"
DEFAULT_S109_REPORT = (
    STAGE7_ROOT
    / "reports"
    / "weekly_coordinate_write_blocker_audit_s109_20260601"
    / "weekly_coordinate_write_blocker_audit.json"
)
DEFAULT_S132_REPORT = STAGE7_ROOT / "reports" / "db_write_lock_gate_s132_20260601" / "db_write_lock_gate.json"
DEFAULT_GEO_COVERAGE_REPORT = (
    STAGE7_ROOT
    / "reports"
    / "weekly_venue_registry_geo_coverage_20260531"
    / "weekly_venue_registry_geo_coverage.json"
)
DEFAULT_REGISTRY = STAGE7_ROOT / "registries" / "weekly_venues_seed.json"
DEFAULT_CURRENT_RELEASE = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release" / "current.json"
DEFAULT_MINIAPP_SQLITE = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "target_specific_db_write_gate_preflight_s133_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_TARGET_SPECIFIC_DB_WRITE_GATE_PREFLIGHT_S133_20260601.md"
DEFAULT_S134_REPORT = (
    STAGE7_ROOT
    / "reports"
    / "rust_club_source_acceptance_s134_20260601"
    / "rust_club_source_acceptance_s134.json"
)
DEFAULT_FRESH_AFTER = "2026-05-22"
SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|token\s*[:=]\s*[^,\s]{8,}|cookie\s*[:=]\s*[^,\s]{8,}|password\s*[:=]\s*[^,\s]{8,}|BEGIN [A-Z ]*PRIVATE KEY)"
)
COORDINATE_FIELDS = {"geo_lng", "geo_lat", "lng", "lat", "longitude", "latitude", "address", "address_full", "geo_source"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def stable_id(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return read_json(path)


def first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def parse_iso_date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text[:10], text):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def current_stale_registry_rows(registry_path: Path, *, fresh_after: str = DEFAULT_FRESH_AFTER) -> list[dict[str, Any]]:
    if not registry_path.exists():
        return []
    fresh_after_date = parse_iso_date(fresh_after)
    if fresh_after_date is None:
        raise ValueError(f"invalid fresh_after date: {fresh_after}")
    registry = read_json(registry_path)
    rows: list[dict[str, Any]] = []
    for row in registry.get("venues", []):
        if first_text(row.get("status")) != "active":
            continue
        verified_at = parse_iso_date(first_text(row.get("last_verified_at"), row.get("geo_verified_at")))
        if verified_at is None or verified_at < fresh_after_date:
            rows.append(
                {
                    "venue_id": first_text(row.get("venue_id")),
                    "canonical_name": first_text(row.get("canonical_name"), row.get("name")),
                    "city": first_text(row.get("city_name"), row.get("city_key")),
                    "address_full": first_text(row.get("address_full"), row.get("address")),
                    "geo_source": first_text(row.get("geo_source"), row.get("geo_provider")),
                    "last_verified_at": first_text(row.get("last_verified_at"), row.get("geo_verified_at")),
                }
            )
    return rows


def s134_source_acceptance_ready(s134: dict[str, Any]) -> bool:
    source = s134.get("source_acceptance") or {}
    registry_write = s134.get("registry_write") or {}
    return bool(
        source.get("ready") is True
        and int(source.get("accepted_count") or 0) >= 2
        and source.get("coordinate_consensus") is True
        and registry_write.get("readback_ok") is True
    )


def s134_selector_window_reconciled(s134: dict[str, Any]) -> bool:
    reconciliation = s134.get("current_release_selector_reconciliation") or {}
    return reconciliation.get("decision") == "selector_absent_due_window_rollover"


def first_coordinate_task(s109: dict[str, Any], task_type: str) -> dict[str, Any]:
    for task in s109.get("next_action_tasks", []):
        if task.get("task_type") == task_type:
            return task
    return {}


def load_registry_row(path: Path, venue_id: str) -> tuple[dict[str, Any] | None, int]:
    if not path.exists():
        return None, 0
    registry = read_json(path)
    venues = registry.get("venues", [])
    for index, row in enumerate(venues):
        if row.get("venue_id") == venue_id:
            return dict(row), index
    return None, len(venues)


def find_current_item(path: Path, item_id: str) -> tuple[dict[str, Any] | None, int]:
    if not path.exists():
        return None, 0
    current = read_json(path)
    items = current.get("items", [])
    for index, item in enumerate(items):
        if item.get("id") == item_id:
            return dict(item), index
    return None, len(items)


def sqlite_coordinate_surface(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "target_path": rel_path(path),
            "exists": False,
            "coordinate_capable_tables": [],
            "rust_selector_hits": 0,
            "write_surface": "not_present",
        }
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
        coordinate_tables: list[dict[str, Any]] = []
        rust_hits = 0
        for table in tables:
            cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            matched = sorted(set(cols).intersection(COORDINATE_FIELDS))
            if matched:
                coordinate_tables.append({"table": table, "coordinate_like_columns": matched})
            if {"display_name", "venue_name"}.intersection(cols):
                text_cols = [col for col in ("display_name", "venue_name") if col in cols]
                for col in text_cols:
                    rust_hits += int(
                        conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} LIKE ?", ("%Rust Club%",)).fetchone()[0]
                    )
    finally:
        conn.close()
    return {
        "target_path": rel_path(path),
        "exists": True,
        "coordinate_capable_tables": coordinate_tables,
        "rust_selector_hits": rust_hits,
        "write_surface": "sqlite_read_only_inspected",
    }


def s132_contract_ready(s132: dict[str, Any]) -> bool:
    summary = s132.get("summary", {})
    contract = s132.get("gate_contract", {})
    required = set(contract.get("required_controls", []))
    has_controls = all(
        any(token in control for control in required)
        for token in ("backup", "busy_timeout", "BEGIN IMMEDIATE", "readback", "rollback")
    )
    return (
        s132.get("decision") == "db_write_lock_gate_ready_report_only"
        and summary.get("all_fixture_scenarios_passed") is True
        and has_controls
    )


def build_registry_preflight(
    *,
    registry_path: Path,
    s109_task: dict[str, Any],
    coverage: dict[str, Any],
    s134: dict[str, Any],
) -> dict[str, Any]:
    venue_id = str(s109_task.get("venue_id") or "rust_club_daqing")
    row, index = load_registry_row(registry_path, venue_id)
    accepted = int(s109_task.get("accepted_provider_result_count", 0) or 0)
    requirements = list(s109_task.get("requirements_before_any_write", []))
    row_status = row.get("status") if row else ""
    evidence_missing = []
    source_ready = s134_source_acceptance_ready(s134)
    if accepted <= 0 and not source_ready:
        evidence_missing.append("provider_accepted_coordinate")
    if row is None:
        evidence_missing.append("registry_row")
    if row and not row.get("address_full"):
        evidence_missing.append("street_level_address_in_registry")
    if row and row_status == "pending_geocode":
        evidence_missing.append("registry_status_active_or_write_ready")
    write_gate_status = "source_acceptance_satisfied_registry_write_readback" if source_ready and not evidence_missing else "blocked_pending_provider_acceptance"
    return {
        "task_id": "s133:coordinate:registry:rust_club_daqing",
        "source_task_id": s109_task.get("task_id", ""),
        "target_kind": "json_registry",
        "target_path": rel_path(registry_path),
        "selector": {"venue_id": venue_id},
        "selector_found": row is not None,
        "selector_index": index if row is not None else None,
        "current_values": {
            "canonical_name": row.get("canonical_name") if row else "",
            "city_name": row.get("city_name") if row else "",
            "address_full": row.get("address_full") if row else "",
            "status": row.get("status") if row else "",
            "geo_lng": row.get("geo_lng") if row else None,
            "geo_lat": row.get("geo_lat") if row else None,
            "geo_source": row.get("geo_source") if row else "",
            "last_verified_at": row.get("last_verified_at") if row else "",
        },
        "candidate_values_from_s109": {
            "address_full": s109_task.get("user_address_candidate", ""),
            "city_name": s109_task.get("city", ""),
            "venue_name": s109_task.get("venue_name", ""),
        },
        "write_fields_after_gate": [
            "address_full",
            "geo_lng",
            "geo_lat",
            "geo_coord_system",
            "geo_source",
            "last_verified_at",
            "status",
            "source_note",
        ],
        "required_evidence_before_write": requirements,
        "evidence_missing_now": evidence_missing,
        "write_gate_status": write_gate_status,
        "production_write_allowed_now": False,
        "s134_source_acceptance": {
            "ready": source_ready,
            "report": rel_path(DEFAULT_S134_REPORT) if DEFAULT_S134_REPORT.exists() else "",
            "accepted_count": int((s134.get("source_acceptance") or {}).get("accepted_count") or 0),
            "registry_readback_ok": bool((s134.get("registry_write") or {}).get("readback_ok")),
        },
        "prewrite_readback_selector": {"venue_id": venue_id, "path": "$.venues[*]"},
        "rollback_contract": "restore exact prewrite registry row by venue_id from backup artifact",
        "coverage_reference": {
            "pending_geocode_count": coverage.get("counts", {}).get("registry_pending_geocode"),
            "known_blocker_count": coverage.get("counts", {}).get("current_missing_geo_known_blockers"),
        },
    }


def build_current_release_preflight(
    *,
    current_release_path: Path,
    s109_task: dict[str, Any],
    coverage: dict[str, Any],
    s134: dict[str, Any],
) -> dict[str, Any]:
    current_ids = list(s109_task.get("current_missing_geo_ids", []))
    item_id = current_ids[0] if current_ids else "rust_club:74c857fda5f80128"
    item, index = find_current_item(current_release_path, item_id)
    coverage_missing = [
        item
        for item in coverage.get("current_missing_geo", [])
        if item.get("id") == item_id or item.get("venue_id") == s109_task.get("venue_id")
    ]
    evidence_missing = []
    selector_window_reconciled = s134_selector_window_reconciled(s134)
    source_ready = s134_source_acceptance_ready(s134)
    if item is None and not selector_window_reconciled:
        evidence_missing.append("selector_not_present_in_current_release_file")
    if int(s109_task.get("accepted_provider_result_count", 0) or 0) <= 0 and not source_ready:
        evidence_missing.append("provider_accepted_coordinate")
    if coverage_missing and not selector_window_reconciled:
        evidence_missing.append("coverage_report_still_records_missing_geo")
    write_gate_status = (
        "selector_reconciled_window_rollover_no_release_write"
        if selector_window_reconciled and source_ready and not evidence_missing
        else "blocked_pending_current_selector_and_provider_acceptance"
    )
    return {
        "task_id": "s133:coordinate:current_release:rust_club_missing_geo",
        "source_task_id": s109_task.get("task_id", ""),
        "target_kind": "json_release",
        "target_path": rel_path(current_release_path),
        "selector": {"id": item_id},
        "selector_found": item is not None,
        "selector_index": index if item is not None else None,
        "current_values": {
            "venue_id": item.get("venue_id") if item else "",
            "venue_name": item.get("venue_name") if item else "",
            "city": item.get("city") if item else "",
            "address": item.get("address") if item else "",
            "geo_lng": item.get("geo_lng") if item else None,
            "geo_lat": item.get("geo_lat") if item else None,
            "geo_source": item.get("geo_source") if item else "",
        },
        "candidate_values_from_s109": {
            "address": s109_task.get("user_address_candidate", ""),
            "city": s109_task.get("city", ""),
            "venue_name": s109_task.get("venue_name", ""),
        },
        "write_fields_after_gate": ["address", "geo_lng", "geo_lat", "geo_source"],
        "required_evidence_before_write": list(s109_task.get("requirements_before_any_write", []))
        + ["current_release_selector_present_or_rebuild_packet_names_rebuilt_output"],
        "evidence_missing_now": evidence_missing,
        "write_gate_status": write_gate_status,
        "production_write_allowed_now": False,
        "s134_selector_reconciliation": (s134.get("current_release_selector_reconciliation") or {}),
        "prewrite_readback_selector": {"id": item_id, "path": "$.items[*]"},
        "rollback_contract": "restore exact prewrite current-release item by id from backup artifact",
        "coverage_reference": {
            "coverage_report_current_missing_geo_rows": len(coverage_missing),
            "current_release_items_in_file": find_current_item_count(current_release_path),
        },
    }


def find_current_item_count(path: Path) -> int:
    if not path.exists():
        return 0
    current = read_json(path)
    return len(current.get("items", []))


def build_stale_registry_preflight(*, registry_path: Path, stale_task: dict[str, Any]) -> dict[str, Any]:
    current_stale_rows = current_stale_registry_rows(registry_path)
    stale_count = len(current_stale_rows) if registry_path.exists() else int(stale_task.get("stale_registry_active_row_count", 0) or 0)
    return {
        "task_id": "s133:coordinate:registry:active_latest_claim_recheck",
        "source_task_id": stale_task.get("task_id", ""),
        "target_kind": "json_registry_batch",
        "target_path": rel_path(registry_path),
        "selector": {"status": "active", "last_verified_at": f"older_than_{DEFAULT_FRESH_AFTER}"},
        "selector_found": stale_count > 0,
        "stale_registry_active_row_count": stale_count,
        "sample_rows": (current_stale_rows or stale_task.get("sample_rows", []))[:10],
        "stale_count_source": "current_registry_readback" if registry_path.exists() else "s109_stale_task_snapshot",
        "write_fields_after_gate": ["last_verified_at", "geo_lng", "geo_lat", "geo_source", "source_note"],
        "required_evidence_before_write": list(stale_task.get("requirements_before_latest_claim", [])),
        "evidence_missing_now": ["fresh_provider_or_current_official_source_recheck"] if stale_count > 0 else [],
        "write_gate_status": "blocked_pending_external_recheck",
        "production_write_allowed_now": False,
        "prewrite_readback_selector": {"path": "$.venues[*]", "status": "active"},
        "rollback_contract": "restore every changed registry row by venue_id from backup artifact",
    }


def build_sqlite_preflight(*, sqlite_path: Path, s132: dict[str, Any]) -> dict[str, Any]:
    surface = sqlite_coordinate_surface(sqlite_path)
    coordinate_capable = bool(surface.get("coordinate_capable_tables"))
    return {
        "task_id": "s133:coordinate:sqlite:atlas_miniapp_surface_check",
        "target_kind": "sqlite",
        **surface,
        "s132_gate_contract_attached": s132_contract_ready(s132),
        "required_write_controls_if_later_used": s132.get("gate_contract", {}).get("required_controls", []),
        "write_gate_status": "not_coordinate_target" if not coordinate_capable else "blocked_until_target_sql_and_readback_selector_defined",
        "production_write_allowed_now": False,
        "prewrite_readback_selector": {},
        "rollback_contract": "S132 SQLite backup/rollback/readback contract must be instantiated per SQL table before any write",
    }


def secret_findings(payload: Any) -> list[dict[str, str]]:
    text = json.dumps(payload, ensure_ascii=False)
    findings = []
    for match in SECRET_RE.finditer(text):
        findings.append({"pattern": "secret_like_text", "sample": match.group(0)[:16] + "..."})
        if len(findings) >= 10:
            break
    return findings


def render_scorecard(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Weekly Target-Specific DB Write Gate Preflight S133",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Target tasks: `{summary['target_task_count']}`",
        f"- Blocked target tasks: `{summary['blocked_target_task_count']}`",
        f"- Write-not-allowed target tasks: `{summary.get('write_not_allowed_target_count', summary['blocked_target_task_count'])}`",
        f"- S132 lock contract ready: `{summary['s132_lock_contract_ready']}`",
        f"- Production write allowed now: `{summary['production_write_allowed_now']}`",
        f"- S134 source acceptance ready: `{summary.get('s134_source_acceptance_ready', False)}`",
        f"- S134 selector window reconciled: `{summary.get('s134_selector_window_reconciled', False)}`",
        f"- Current release selector found: `{summary['current_release_selector_found']}`",
        f"- Registry selector found: `{summary['registry_selector_found']}`",
        f"- SQLite coordinate target found: `{summary['sqlite_coordinate_target_found']}`",
        f"- Finding count: `{report['finding_count']}`",
        "",
        "## Target Tasks",
        "",
    ]
    for task in report["target_tasks"]:
        lines.append(
            f"- `{task['task_id']}`: `{task['write_gate_status']}`, selector_found=`{task.get('selector_found', '')}`"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Report-only preflight. No DB1/DB2/DB3 mutation, no release JSON mutation, no registry mutation, no deploy/upload/review, no map provider/API call, no model call, no cookie/token value read.",
            "- This is not a blocker skip: each target surface has an explicit selector, field list, missing evidence list, rollback contract, and next repair gate.",
            "- The next repair story must either obtain provider-accepted coordinate evidence and rerun this packet, or keep the specific target blocked with fresh failure evidence.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_preflight(
    *,
    s109_report_path: Path,
    s132_report_path: Path,
    s134_report_path: Path = DEFAULT_S134_REPORT,
    geo_coverage_report_path: Path,
    registry_path: Path,
    current_release_path: Path,
    miniapp_sqlite_path: Path,
    out_dir: Path,
    scorecard_path: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    s109 = read_json(s109_report_path)
    s132 = read_json(s132_report_path)
    s134 = read_optional_json(s134_report_path)
    coverage = read_json(geo_coverage_report_path) if geo_coverage_report_path.exists() else {}
    rust_task = first_coordinate_task(s109, "rust_club_provider_crosscheck")
    stale_task = first_coordinate_task(s109, "stale_registry_latest_claim_recheck")
    if not rust_task:
        raise ValueError("S109 rust_club_provider_crosscheck task not found")
    if not stale_task:
        raise ValueError("S109 stale_registry_latest_claim_recheck task not found")

    target_tasks = [
        build_registry_preflight(registry_path=registry_path, s109_task=rust_task, coverage=coverage, s134=s134),
        build_current_release_preflight(current_release_path=current_release_path, s109_task=rust_task, coverage=coverage, s134=s134),
        build_stale_registry_preflight(registry_path=registry_path, stale_task=stale_task),
        build_sqlite_preflight(sqlite_path=miniapp_sqlite_path, s132=s132),
    ]
    s132_ready = s132_contract_ready(s132)
    s134_ready = s134_source_acceptance_ready(s134)
    s134_reconciled = s134_selector_window_reconciled(s134)
    next_story = "S136" if s134_ready and s134_reconciled else "S134"
    next_safe_action = (
        {
            "story_id": "S136",
            "action": "run stale active-registry latest-claim recheck with S132 lock/readback/rollback controls before any batch coordinate freshness write",
            "must_not_skip": [
                "59 stale active registry rows still require fresh provider or current official source recheck",
                "batch registry writes still require backup, bounded lock handling, postwrite readback, and rollback contract",
                "Rust Club source acceptance does not clear unrelated stale-coordinate freshness rows",
            ],
        }
        if next_story == "S136"
        else {
            "story_id": "S134",
            "action": "run bounded provider/source acceptance repair for rust_club_daqing, then rerun S133 before any write",
            "must_not_skip": [
                "provider acceptance cannot be replaced by user address alone",
                "current release selector drift must be reconciled before release JSON write",
                "registry pending_geocode status must not be promoted without accepted coordinate evidence",
            ],
        }
    )
    registry_task = target_tasks[0]
    current_task = target_tasks[1]
    sqlite_task = target_tasks[3]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "target_specific_db_write_gate_preflight_ready_report_only",
        "inputs": {
            "s109_coordinate_blocker_report": rel_path(s109_report_path),
            "s132_db_write_lock_gate_report": rel_path(s132_report_path),
            "s134_source_acceptance_report": rel_path(s134_report_path) if s134_report_path.exists() else "",
            "geo_coverage_report": rel_path(geo_coverage_report_path),
            "registry_path": rel_path(registry_path),
            "current_release_path": rel_path(current_release_path),
            "miniapp_sqlite_path": rel_path(miniapp_sqlite_path),
        },
        "outputs": {
            "report": rel_path(out_dir / "target_specific_db_write_gate_preflight.json"),
            "tasks": rel_path(out_dir / "target_specific_db_write_gate_tasks.jsonl"),
            "scorecard": rel_path(scorecard_path),
        },
        "s132_gate_contract": {
            "ready": s132_ready,
            "config": s132.get("gate_contract", {}).get("config", {}),
            "required_controls": s132.get("gate_contract", {}).get("required_controls", []),
            "forbidden_shortcuts": s132.get("gate_contract", {}).get("forbidden_shortcuts", []),
        },
        "target_tasks": target_tasks,
        "summary": {
            "target_task_count": len(target_tasks),
            "blocked_target_task_count": sum(1 for task in target_tasks if str(task.get("write_gate_status", "")).startswith("blocked")),
            "write_not_allowed_target_count": sum(1 for task in target_tasks if not task["production_write_allowed_now"]),
            "s132_lock_contract_ready": s132_ready,
            "production_write_allowed_now": False,
            "registry_selector_found": bool(registry_task.get("selector_found")),
            "current_release_selector_found": bool(current_task.get("selector_found")),
            "sqlite_coordinate_target_found": bool(sqlite_task.get("coordinate_capable_tables")),
            "provider_accepted_count": int(rust_task.get("accepted_provider_result_count", 0) or 0),
            "provider_review_count": int(rust_task.get("review_provider_result_count", 0) or 0),
            "s134_source_acceptance_ready": s134_ready,
            "s134_selector_window_reconciled": s134_reconciled,
            "stale_registry_active_row_count": int(target_tasks[2].get("stale_registry_active_row_count", 0) or 0),
            "all_target_tasks_have_selectors": all(bool(task.get("selector") or task.get("target_path")) for task in target_tasks),
            "all_target_tasks_have_rollback_contracts": all(bool(task.get("rollback_contract")) for task in target_tasks),
        },
        "boundary": {
            "report_only": True,
            "db1_mutation": False,
            "db2_mutation": False,
            "db3_mutation": False,
            "sqlite_mutation": False,
            "registry_or_release_mutation": False,
            "deploy_upload_review": False,
            "provider_or_geocode_call": False,
            "model_call_performed": False,
            "cookie_values_read": False,
            "token_values_read": False,
            "broad_disk_scan": False,
        },
        "next_story": next_story,
        "next_safe_action": next_safe_action,
        "secret_like_findings": [],
        "finding_count": 0,
    }
    findings = secret_findings({"report": report, "tasks": target_tasks})
    report["secret_like_findings"] = findings
    report["finding_count"] = len(findings)
    atomic_write_json(out_dir / "target_specific_db_write_gate_preflight.json", report)
    atomic_write_jsonl(out_dir / "target_specific_db_write_gate_tasks.jsonl", target_tasks)
    atomic_write_text(scorecard_path, render_scorecard(report))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s109-report", type=Path, default=DEFAULT_S109_REPORT)
    parser.add_argument("--s132-report", type=Path, default=DEFAULT_S132_REPORT)
    parser.add_argument("--s134-report", type=Path, default=DEFAULT_S134_REPORT)
    parser.add_argument("--geo-coverage-report", type=Path, default=DEFAULT_GEO_COVERAGE_REPORT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--current-release", type=Path, default=DEFAULT_CURRENT_RELEASE)
    parser.add_argument("--miniapp-sqlite", type=Path, default=DEFAULT_MINIAPP_SQLITE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_preflight(
        s109_report_path=args.s109_report,
        s132_report_path=args.s132_report,
        s134_report_path=args.s134_report,
        geo_coverage_report_path=args.geo_coverage_report,
        registry_path=args.registry,
        current_release_path=args.current_release,
        miniapp_sqlite_path=args.miniapp_sqlite,
        out_dir=args.out_dir,
        scorecard_path=args.scorecard,
    )
    print(json.dumps({"decision": report["decision"], "summary": report["summary"]}, ensure_ascii=False, sort_keys=True))
    return 0 if report["finding_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
