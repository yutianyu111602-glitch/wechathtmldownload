#!/usr/bin/env python3
"""Build and optionally apply the S136 stale active-registry latest-claim recheck.

The input lane is the S133 stale active registry task. This script uses only
local current-release source evidence. It does not call map providers, crawl
external pages, touch DB1/DB2/DB3/SQLite, deploy, upload, or read secrets.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import tempfile
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "stale_active_registry_latest_claim_recheck_s136.v1"
DEFAULT_S133_TASKS = (
    STAGE7_ROOT
    / "reports"
    / "target_specific_db_write_gate_preflight_s133_20260601"
    / "target_specific_db_write_gate_tasks.jsonl"
)
DEFAULT_S132_REPORT = STAGE7_ROOT / "reports" / "db_write_lock_gate_s132_20260601" / "db_write_lock_gate.json"
DEFAULT_REGISTRY = STAGE7_ROOT / "registries" / "weekly_venues_seed.json"
DEFAULT_CURRENT_RELEASE = ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release" / "current.json"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "stale_active_registry_latest_claim_recheck_s136_20260601"
DEFAULT_SCORECARD = ROOT / "reports" / "WEEKLY_STALE_ACTIVE_REGISTRY_LATEST_CLAIM_RECHECK_S136_20260601.md"
DEFAULT_FRESH_AFTER = "2026-05-22"
TAXI_GRADE_DRIFT_METERS = 120.0


def now_cst() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def today_cst() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def write_json(path: Path, payload: Any) -> None:
    write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    write_text_atomic(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def first(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            nested = first(*value)
            if nested:
                return nested
            continue
        text = str(value or "").strip()
        if text:
            return text
    return ""


def parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text[:10], text):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def finite_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def coordinate(row: dict[str, Any]) -> tuple[float | None, float | None]:
    lng = finite_float(first(row.get("geo_lng"), row.get("lng"), row.get("longitude"), row.get("gcj02_lng")))
    lat = finite_float(first(row.get("geo_lat"), row.get("lat"), row.get("latitude"), row.get("gcj02_lat")))
    return lng, lat


def has_china_coordinate(row: dict[str, Any]) -> bool:
    lng, lat = coordinate(row)
    return lng is not None and lat is not None and 73.0 <= lng <= 135.5 and 18.0 <= lat <= 54.5


def meters_between(a_lng: float, a_lat: float, b_lng: float, b_lat: float) -> float:
    radius = 6371000.0
    phi1 = math.radians(a_lat)
    phi2 = math.radians(b_lat)
    d_phi = math.radians(b_lat - a_lat)
    d_lambda = math.radians(b_lng - a_lng)
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def address(row: dict[str, Any]) -> str:
    return first(row.get("address_full"), row.get("address"), row.get("venue_address"))


def normalize_address(value: str) -> str:
    replacements = {
        "臺": "台",
        "號": "号",
        "樓": "楼",
        "層": "层",
        "，": "",
        ",": "",
        "。": "",
        ".": "",
        " ": "",
        "\t": "",
        "\n": "",
        "（": "(",
        "）": ")",
        "-": "",
        "－": "",
    }
    text = str(value or "").strip().lower()
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def source_article_hash(item: dict[str, Any]) -> str:
    source_article = item.get("source_article") if isinstance(item.get("source_article"), dict) else {}
    source_action = item.get("source_action") if isinstance(item.get("source_action"), dict) else {}
    return first(
        source_article.get("url_hash"),
        source_action.get("url_hash"),
        item.get("source_url_hash"),
        item.get("article_id"),
        item.get("id"),
    )


def item_evidence_date(item: dict[str, Any]) -> date | None:
    candidates = [
        item.get("source_published_at"),
        item.get("post_date"),
        item.get("event_date_start"),
        item.get("event_date_iso_guess"),
    ]
    parsed = [value for value in (parse_date(candidate) for candidate in candidates) if value is not None]
    return max(parsed) if parsed else None


def is_source_bound_current_item(item: dict[str, Any], fresh_after_date: date) -> bool:
    source_article = item.get("source_article") if isinstance(item.get("source_article"), dict) else {}
    source_action = item.get("source_action") if isinstance(item.get("source_action"), dict) else {}
    has_source_ref = bool(source_article_hash(item)) and (
        bool(source_article.get("url_hash"))
        or source_action.get("available") is True
        or first(item.get("detail_url"), item.get("detail_path"))
    )
    evidence_date = item_evidence_date(item)
    return bool(has_source_ref and evidence_date is not None and evidence_date >= fresh_after_date)


def stale_registry_rows(registry: dict[str, Any], fresh_after: str) -> list[dict[str, Any]]:
    fresh_after_date = parse_date(fresh_after)
    if fresh_after_date is None:
        raise ValueError(f"invalid fresh_after: {fresh_after}")
    rows: list[dict[str, Any]] = []
    for row in registry.get("venues", []):
        if first(row.get("status")) != "active":
            continue
        verified_at = parse_date(first(row.get("last_verified_at"), row.get("geo_verified_at")))
        if verified_at is None or verified_at < fresh_after_date:
            rows.append(row)
    return rows


def current_items_by_venue(current_release: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in current_release.get("items", []):
        venue_id = first(item.get("venue_id"))
        if venue_id:
            grouped[venue_id].append(item)
    return grouped


def short_item(item: dict[str, Any]) -> dict[str, Any]:
    lng, lat = coordinate(item)
    source_date = item_evidence_date(item)
    return {
        "id": first(item.get("id"), item.get("event_id")),
        "article_id": first(item.get("article_id")),
        "event_date_start": first(item.get("event_date_start"), item.get("event_date_iso_guess")),
        "source_published_at": first(item.get("source_published_at"), item.get("post_date")),
        "source_url_hash": source_article_hash(item),
        "source_evidence_date": source_date.isoformat() if source_date else "",
        "address": address(item),
        "geo_lng": lng,
        "geo_lat": lat,
        "address_source": first(item.get("address_source")),
        "source_account_name": first(item.get("source_account_name"), item.get("account")),
    }


def build_row_decision(
    registry_row: dict[str, Any],
    current_items: list[dict[str, Any]],
    *,
    fresh_after_date: date,
) -> dict[str, Any]:
    venue_id = first(registry_row.get("venue_id"))
    reg_lng, reg_lat = coordinate(registry_row)
    reg_address = address(registry_row)
    reg_address_norm = normalize_address(reg_address)
    source_items = [
        item
        for item in current_items
        if is_source_bound_current_item(item, fresh_after_date)
    ]
    evidence_items = [short_item(item) for item in source_items]
    blocking_reasons: list[str] = []

    if not current_items:
        blocking_reasons.append("no_current_release_item_for_venue")
    if not source_items:
        blocking_reasons.append("no_fresh_source_bound_current_item")
    if not reg_address_norm:
        blocking_reasons.append("registry_address_missing")
    if reg_lng is None or reg_lat is None:
        blocking_reasons.append("registry_coordinate_missing")

    address_norms = sorted({normalize_address(address(item)) for item in source_items if address(item)})
    if source_items and not address_norms:
        blocking_reasons.append("current_source_address_missing")
    if len(address_norms) > 1:
        blocking_reasons.append("current_source_address_conflict")
    if address_norms and reg_address_norm and any(value != reg_address_norm for value in address_norms):
        blocking_reasons.append("current_source_address_differs_from_registry")

    drift_meters: list[float] = []
    if reg_lng is not None and reg_lat is not None:
        for item in source_items:
            item_lng, item_lat = coordinate(item)
            if item_lng is None or item_lat is None:
                blocking_reasons.append("current_source_coordinate_missing")
                continue
            drift_meters.append(meters_between(reg_lng, reg_lat, item_lng, item_lat))
    if drift_meters and max(drift_meters) > TAXI_GRADE_DRIFT_METERS:
        blocking_reasons.append("current_source_coordinate_drift_exceeds_taxi_grade")

    current_coords = {
        (round(coordinate(item)[0] or 0, 6), round(coordinate(item)[1] or 0, 6))
        for item in source_items
        if has_china_coordinate(item)
    }
    if len(current_coords) > 1:
        blocking_reasons.append("current_source_coordinate_conflict")

    blocking_reasons = sorted(set(blocking_reasons))
    ready = not blocking_reasons and bool(source_items)
    status = "write_ready_current_source_confirms_same_address_coordinate" if ready else "blocked_pending_fresh_latest_claim_evidence"
    source_ids = [row["article_id"] or row["id"] for row in evidence_items]
    note_ids = ", ".join(source_ids[:3])
    if len(source_ids) > 3:
        note_ids += f", +{len(source_ids) - 3} more"
    source_note = (
        f"{today_cst()} S136 current-release source recheck: {len(source_ids)} source-bound item(s) "
        f"confirmed the same registry address and coordinate; article_ids={note_ids}; "
        f"previous_last_verified_at={first(registry_row.get('last_verified_at')) or 'empty'}."
    )
    return {
        "venue_id": venue_id,
        "canonical_name": first(registry_row.get("canonical_name"), registry_row.get("name")),
        "city": first(registry_row.get("city_name"), registry_row.get("city_key")),
        "previous_last_verified_at": first(registry_row.get("last_verified_at"), registry_row.get("geo_verified_at")),
        "registry_address": reg_address,
        "registry_geo_lng": reg_lng,
        "registry_geo_lat": reg_lat,
        "registry_geo_source": first(registry_row.get("geo_source")),
        "current_item_count": len(current_items),
        "source_bound_current_item_count": len(source_items),
        "current_source_items": evidence_items[:5],
        "max_drift_meters": round(max(drift_meters), 3) if drift_meters else None,
        "address_match_basis": "normalized_exact" if ready else "",
        "write_gate_status": status,
        "write_ready": ready,
        "blocking_reasons": blocking_reasons,
        "write_fields_after_gate": ["last_verified_at", "source_note"],
        "candidate_write": {
            "last_verified_at": today_cst(),
            "source_note": source_note,
            "preserve_geo_lng": reg_lng,
            "preserve_geo_lat": reg_lat,
            "preserve_geo_source": first(registry_row.get("geo_source")),
        },
        "rollback_selector": {"venue_id": venue_id, "path": "$.venues[*]"},
    }


def s132_contract_ready(s132: dict[str, Any]) -> bool:
    summary = s132.get("summary", {})
    required_controls = set((s132.get("gate_contract") or {}).get("required_controls", []))
    return bool(
        s132.get("decision") == "db_write_lock_gate_ready_report_only"
        and summary.get("all_fixture_scenarios_passed") is True
        and any("backup" in item for item in required_controls)
        and any("readback" in item for item in required_controls)
        and any("rollback" in item for item in required_controls)
    )


class FileLock:
    def __init__(self, path: Path, *, attempts: int = 3, sleep_ms: int = 50) -> None:
        self.path = path
        self.attempts = attempts
        self.sleep_ms = sleep_ms
        self.fd: int | None = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, self.attempts + 1):
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, f"pid={os.getpid()} acquired_at={now_cst()}\n".encode("utf-8"))
                return self
            except FileExistsError:
                if attempt == self.attempts:
                    raise TimeoutError(f"lock busy after {self.attempts} attempts: {self.path}")
                time.sleep(self.sleep_ms / 1000.0)
        raise TimeoutError(f"lock busy: {self.path}")

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def apply_registry_write(
    *,
    registry_path: Path,
    registry: dict[str, Any],
    ready_rows: list[dict[str, Any]],
    out_dir: Path,
) -> dict[str, Any]:
    if not ready_rows:
        return {"applied": False, "reason": "no_write_ready_rows", "write_count": 0}
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = out_dir / f"backup_before_stale_registry_latest_claim_s136_{stamp}.json"
    lock_path = registry_path.with_name(registry_path.name + ".s136.lock")
    ready_by_id = {row["venue_id"]: row for row in ready_rows}
    shutil.copy2(registry_path, backup_path)
    with FileLock(lock_path):
        live_registry = read_json(registry_path)
        changed_ids: list[str] = []
        for venue in live_registry.get("venues", []):
            venue_id = first(venue.get("venue_id"))
            candidate = ready_by_id.get(venue_id)
            if not candidate:
                continue
            previous_note = first(venue.get("source_note"))
            new_note = candidate["candidate_write"]["source_note"]
            venue["last_verified_at"] = candidate["candidate_write"]["last_verified_at"]
            venue["source_note"] = f"{previous_note} | {new_note}" if previous_note else new_note
            changed_ids.append(venue_id)
        write_json(registry_path, live_registry)

    readback = read_json(registry_path)
    readback_by_id = {first(row.get("venue_id")): row for row in readback.get("venues", [])}
    failed_ids = [
        venue_id
        for venue_id in changed_ids
        if first(readback_by_id.get(venue_id, {}).get("last_verified_at")) != today_cst()
        or "S136 current-release source recheck" not in first(readback_by_id.get(venue_id, {}).get("source_note"))
    ]
    return {
        "applied": True,
        "write_count": len(changed_ids),
        "backup_path": rel_path(backup_path),
        "lock_path": rel_path(lock_path),
        "readback_ok": not failed_ids and len(changed_ids) == len(ready_rows),
        "changed_venue_ids": changed_ids,
        "failed_readback_venue_ids": failed_ids,
    }


def render_scorecard(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Weekly Stale Active Registry Latest-Claim Recheck S136",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Expected stale rows from S133: `{summary['expected_stale_registry_rows_from_s133']}`",
        f"- Actual stale rows inspected: `{summary['actual_stale_registry_rows_inspected']}`",
        f"- Write-ready rows: `{summary['write_ready_count']}`",
        f"- Blocked rows: `{summary['blocked_count']}`",
        f"- Registry write applied: `{report['registry_write'].get('applied', False)}`",
        f"- Registry write count: `{report['registry_write'].get('write_count', 0)}`",
        f"- S132 lock/readback/rollback contract ready: `{summary['s132_lock_contract_ready']}`",
        f"- Finding count: `{report['finding_count']}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in sorted(summary["status_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Boundary", ""])
    lines.append(
        "- No DB1/DB2/DB3/SQLite mutation, no release JSON write, no deploy/upload/review, no external crawl, no map provider call, no model call, no cookie/token value read."
    )
    lines.append(
        "- Registry writes, when applied, are limited to `last_verified_at` and `source_note` for rows with fresh source-bound current-release evidence, same normalized address, and coordinate drift within taxi-grade threshold."
    )
    lines.extend(["", "## Next", ""])
    if summary["blocked_count"]:
        lines.append(
            f"- Continue S136 with a bounded source/provider acquisition lane for the remaining `{summary['blocked_count']}` blocked rows; do not mark them fresh without new evidence."
        )
    else:
        lines.append("- Rerun coordinate freshness and deploy preflight gates; all stale registry rows in this S136 lane are cleared.")
    return "\n".join(lines) + "\n"


def build_report(
    *,
    s133_tasks_path: Path,
    s132_report_path: Path,
    registry_path: Path,
    current_release_path: Path,
    out_dir: Path,
    scorecard_path: Path,
    apply_write: bool,
    fresh_after: str,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    s133_tasks = read_jsonl(s133_tasks_path)
    stale_task = next((task for task in s133_tasks if task.get("task_id") == "s133:coordinate:registry:active_latest_claim_recheck"), {})
    if not stale_task:
        raise ValueError("S133 active latest-claim task not found")
    s132 = read_json(s132_report_path)
    registry = read_json(registry_path)
    current = read_json(current_release_path)
    fresh_after_date = parse_date(fresh_after)
    if fresh_after_date is None:
        raise ValueError(f"invalid fresh_after: {fresh_after}")

    stale_rows = stale_registry_rows(registry, fresh_after)
    current_by_venue = current_items_by_venue(current)
    decisions = [
        build_row_decision(row, current_by_venue.get(first(row.get("venue_id")), []), fresh_after_date=fresh_after_date)
        for row in stale_rows
    ]
    ready_rows = [row for row in decisions if row["write_ready"]]
    blocked_rows = [row for row in decisions if not row["write_ready"]]
    expected_count = int(stale_task.get("stale_registry_active_row_count") or 0)
    findings: list[dict[str, Any]] = []
    if expected_count != len(stale_rows):
        findings.append(
            {
                "finding": "s133_expected_count_mismatch_current_registry",
                "expected_from_s133": expected_count,
                "actual_current_registry": len(stale_rows),
            }
        )
    if ready_rows and not s132_contract_ready(s132):
        findings.append({"finding": "s132_lock_contract_not_ready_for_registry_write"})

    registry_write = {"applied": False, "write_count": 0}
    if apply_write and ready_rows and not findings:
        registry_write = apply_registry_write(registry_path=registry_path, registry=registry, ready_rows=ready_rows, out_dir=out_dir)
        if not registry_write.get("readback_ok"):
            findings.append({"finding": "registry_write_readback_failed", "details": registry_write})
    elif apply_write and findings:
        registry_write = {"applied": False, "write_count": 0, "reason": "findings_blocked_write"}

    status_counts = Counter(row["write_gate_status"] for row in decisions)
    blocking_counts = Counter(reason for row in blocked_rows for reason in row["blocking_reasons"])
    decision = (
        "stale_active_registry_latest_claim_recheck_partial_registry_write_applied"
        if registry_write.get("applied") and blocked_rows
        else "stale_active_registry_latest_claim_recheck_registry_write_applied"
        if registry_write.get("applied")
        else "stale_active_registry_latest_claim_recheck_ready_candidates_report_only"
        if ready_rows
        else "stale_active_registry_latest_claim_recheck_blocked_report_only"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_cst(),
        "decision": decision,
        "inputs": {
            "s133_tasks": rel_path(s133_tasks_path),
            "s132_report": rel_path(s132_report_path),
            "registry": rel_path(registry_path),
            "current_release": rel_path(current_release_path),
        },
        "outputs": {
            "report": rel_path(out_dir / "stale_active_registry_latest_claim_recheck_s136.json"),
            "rows": rel_path(out_dir / "stale_active_registry_latest_claim_recheck_rows_s136.jsonl"),
            "scorecard": rel_path(scorecard_path),
        },
        "freshness_policy": {
            "fresh_after": fresh_after,
            "taxi_grade_drift_meters": TAXI_GRADE_DRIFT_METERS,
        },
        "summary": {
            "expected_stale_registry_rows_from_s133": expected_count,
            "actual_stale_registry_rows_inspected": len(stale_rows),
            "write_ready_count": len(ready_rows),
            "blocked_count": len(blocked_rows),
            "status_counts": dict(status_counts),
            "blocking_reason_counts": dict(blocking_counts),
            "s132_lock_contract_ready": s132_contract_ready(s132),
            "registry_write_requested": apply_write,
        },
        "registry_write": registry_write,
        "ready_venue_ids": [row["venue_id"] for row in ready_rows],
        "blocked_venue_ids": [row["venue_id"] for row in blocked_rows],
        "boundary": {
            "report_only": not registry_write.get("applied"),
            "registry_mutation": bool(registry_write.get("applied")),
            "db1_mutation": False,
            "db2_mutation": False,
            "db3_mutation": False,
            "sqlite_mutation": False,
            "release_json_mutation": False,
            "deploy_upload_review": False,
            "provider_or_geocode_call": False,
            "external_crawl": False,
            "model_call": False,
            "cookie_values_read": False,
            "token_values_read": False,
            "broad_disk_scan": False,
        },
        "next_safe_action": (
            "continue S136 source/provider acquisition for blocked stale registry rows"
            if blocked_rows
            else "rerun coordinate freshness and deploy preflight gates"
        ),
        "findings": findings,
        "finding_count": len(findings),
    }
    write_json(out_dir / "stale_active_registry_latest_claim_recheck_s136.json", report)
    write_jsonl(out_dir / "stale_active_registry_latest_claim_recheck_rows_s136.jsonl", decisions)
    write_text_atomic(scorecard_path, render_scorecard(report))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s133-tasks", type=Path, default=DEFAULT_S133_TASKS)
    parser.add_argument("--s132-report", type=Path, default=DEFAULT_S132_REPORT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--current-release", type=Path, default=DEFAULT_CURRENT_RELEASE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--fresh-after", default=DEFAULT_FRESH_AFTER)
    parser.add_argument("--apply-registry-write", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(
        s133_tasks_path=args.s133_tasks,
        s132_report_path=args.s132_report,
        registry_path=args.registry,
        current_release_path=args.current_release,
        out_dir=args.out_dir,
        scorecard_path=args.scorecard,
        apply_write=args.apply_registry_write,
        fresh_after=args.fresh_after,
    )
    print(json.dumps({"decision": report["decision"], "summary": report["summary"], "registry_write": report["registry_write"]}, ensure_ascii=False, sort_keys=True))
    return 0 if report["finding_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
