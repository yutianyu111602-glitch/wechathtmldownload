#!/usr/bin/env python3
"""Build the no-write S136 source/provider acquisition queue for remaining stale venues.

This script turns the blocked rows from S136 into executable tasks. It may mine
the local expanded source pack, but it does not crawl, call map providers, call
models, read cookies/tokens, mutate DB1/DB2/DB3/SQLite, or write the venue
registry. DB2/external-link routes are documented as Docker resident weapons
controlled by db2ctl/profile gates, not as one monolithic skill script.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "stale_registry_source_acquisition_queue_s136.v1"
DEFAULT_S136_REPORT = (
    STAGE7_ROOT
    / "reports"
    / "stale_active_registry_latest_claim_recheck_s136_20260601"
    / "stale_active_registry_latest_claim_recheck_s136.json"
)
DEFAULT_S136_ROWS = (
    STAGE7_ROOT
    / "reports"
    / "stale_active_registry_latest_claim_recheck_s136_20260601"
    / "stale_active_registry_latest_claim_recheck_rows_s136.jsonl"
)
DEFAULT_SOURCE_PACK = (
    STAGE7_ROOT
    / "longrun"
    / "WEEKLY_ACTIVITY_EXPANDED_PACK_20260531"
    / "weekly_activity_recommendation_candidates.jsonl"
)
DEFAULT_REGISTRY = STAGE7_ROOT / "registries" / "weekly_venues_seed.json"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "stale_registry_source_acquisition_queue_s136_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_STALE_REGISTRY_SOURCE_ACQUISITION_QUEUE_S136_20260601.md"
DEFAULT_FRESH_AFTER = "2026-05-22"
DB2_WEAPONS_WORKTREE = Path(r"C:\code\.worktrees\wechathtmldownload\20260601-db2-weapons-containers")
DB2CTL_PATH = DB2_WEAPONS_WORKTREE / "tools" / "stage7_rewrite" / "scripts" / "db2ctl.py"
DB2_COMPOSE_PATH = DB2_WEAPONS_WORKTREE / "tools" / "stage7_rewrite" / "db2_weapons" / "compose.yaml"
DB2_WEAPONS_README = DB2_WEAPONS_WORKTREE / "tools" / "stage7_rewrite" / "db2_weapons" / "README.md"
MODULE_LOG = Path(r"C:\code\docs\ops\module-registration-log-20260518.md")
WEAPON_CATALOG = r"\\wsl.localhost\Ubuntu\home\pc\reports\WEAPON_CATALOG_20260601.md"
ARSENAL_SKILL = Path(r"C:\Users\pc\.codex\skills\external-link-db2-arsenal\SKILL.md")
TAXI_GRADE_DRIFT_METERS = 120.0


def now_cst() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


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


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


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


def meters_between(a_lng: float, a_lat: float, b_lng: float, b_lat: float) -> float:
    radius = 6371000.0
    phi1 = math.radians(a_lat)
    phi2 = math.radians(b_lat)
    d_phi = math.radians(b_lat - a_lat)
    d_lambda = math.radians(b_lng - a_lng)
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def normalize_text(value: str) -> str:
    text = str(value or "").strip().lower()
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
        "_": "",
        "·": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def split_tokens(value: str) -> list[str]:
    tokens = [part for part in re.split(r"[^0-9a-zA-Z\u4e00-\u9fff]+", str(value or "").lower()) if len(part) >= 2]
    return sorted(set(tokens))


def row_coordinate(row: dict[str, Any]) -> tuple[float | None, float | None]:
    return (
        finite_float(first(row.get("geo_lng"), row.get("lng"), row.get("longitude"))),
        finite_float(first(row.get("geo_lat"), row.get("lat"), row.get("latitude"))),
    )


def source_text(row: dict[str, Any]) -> str:
    evidence = row.get("evidence") if isinstance(row.get("evidence"), list) else []
    venues = row.get("venue") if isinstance(row.get("venue"), list) else []
    cities = row.get("city") if isinstance(row.get("city"), list) else []
    return " ".join(
        [
            first(row.get("article_id"), row.get("queue_id")),
            first(row.get("title")),
            first(row.get("account_key")),
            first(row.get("address")),
            " ".join(str(item) for item in venues[:5]),
            " ".join(str(item) for item in cities[:5]),
            " ".join(str(item) for item in evidence[:12]),
        ]
    )


def source_date(row: dict[str, Any]) -> date | None:
    candidates = [row.get("post_date"), row.get("event_date_start")]
    for key in ("event_date_text", "date_text"):
        value = row.get(key)
        if isinstance(value, list):
            candidates.extend(value)
        else:
            candidates.append(value)
    parsed = [item for item in (parse_date(candidate) for candidate in candidates) if item is not None]
    return max(parsed) if parsed else None


def filter_currently_stale_rows(
    rows: list[dict[str, Any]],
    *,
    registry_path: Path | None,
    fresh_after: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if registry_path is None or not registry_path.exists():
        return rows, []
    fresh_after_date = parse_date(fresh_after)
    if fresh_after_date is None:
        raise ValueError(f"invalid fresh_after: {fresh_after}")
    registry = read_json(registry_path)
    registry_by_id = {first(row.get("venue_id")): row for row in registry.get("venues", [])}
    stale: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in rows:
        venue_id = first(row.get("venue_id"))
        registry_row = registry_by_id.get(venue_id)
        verified_at = parse_date(first((registry_row or {}).get("last_verified_at"), (registry_row or {}).get("geo_verified_at")))
        if verified_at is not None and verified_at >= fresh_after_date:
            skipped.append({"venue_id": venue_id, "reason": "already_fresh_in_current_registry", "last_verified_at": verified_at.isoformat()})
        else:
            stale.append(row)
    return stale, skipped


def short_source_hit(row: dict[str, Any], *, match_basis: str, drift_meters: float | None, status: str) -> dict[str, Any]:
    return {
        "article_id": first(row.get("article_id"), row.get("queue_id")),
        "queue_id": first(row.get("queue_id")),
        "account_key": first(row.get("account_key")),
        "title": first(row.get("title"))[:180],
        "source_url_present": bool(first(row.get("source_url"))),
        "post_date": first(row.get("post_date")),
        "source_evidence_date": source_date(row).isoformat() if source_date(row) else "",
        "city": first(row.get("city")),
        "venue": first(row.get("venue")),
        "address": first(row.get("address")),
        "geo_lng": finite_float(row.get("geo_lng")),
        "geo_lat": finite_float(row.get("geo_lat")),
        "match_basis": match_basis,
        "drift_meters": round(drift_meters, 3) if drift_meters is not None else None,
        "status": status,
    }


def load_source_pack_candidates(
    path: Path,
    blocked_rows: list[dict[str, Any]],
    *,
    fresh_after: str,
    max_hits_per_venue: int = 8,
) -> dict[str, list[dict[str, Any]]]:
    if not path.exists():
        return {row["venue_id"]: [] for row in blocked_rows}
    fresh_after_date = parse_date(fresh_after)
    if fresh_after_date is None:
        raise ValueError(f"invalid fresh_after: {fresh_after}")

    targets = []
    for row in blocked_rows:
        targets.append(
            {
                "venue_id": first(row.get("venue_id")),
                "name": first(row.get("canonical_name")),
                "city": first(row.get("city")),
                "address": first(row.get("registry_address")),
                "address_norm": normalize_text(first(row.get("registry_address"))),
                "name_norm": normalize_text(first(row.get("canonical_name"))),
                "name_tokens": split_tokens(first(row.get("canonical_name"))),
                "lng": finite_float(row.get("registry_geo_lng")),
                "lat": finite_float(row.get("registry_geo_lat")),
            }
        )
    hits: dict[str, list[dict[str, Any]]] = {target["venue_id"]: [] for target in targets}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                source_row = json.loads(line)
            except json.JSONDecodeError:
                continue
            evidence_date = source_date(source_row)
            if evidence_date is None or evidence_date < fresh_after_date:
                continue
            combined = source_text(source_row)
            combined_norm = normalize_text(combined)
            source_address = first(source_row.get("address"))
            source_address_norm = normalize_text(source_address)
            source_lng, source_lat = row_coordinate(source_row)
            for target in targets:
                if len(hits[target["venue_id"]]) >= max_hits_per_venue:
                    continue
                match_basis = ""
                if target["address_norm"] and source_address_norm == target["address_norm"]:
                    match_basis = "address_normalized_exact"
                elif target["address_norm"] and target["address_norm"] in combined_norm:
                    match_basis = "address_mentioned_in_source_text"
                elif target["name_norm"] and target["name_norm"] in combined_norm:
                    match_basis = "venue_name_mentioned_in_source_text"
                else:
                    token_hits = [token for token in target["name_tokens"] if token and token in combined_norm]
                    if token_hits and first(source_row.get("city")) and target["city"] and target["city"] in first(source_row.get("city")):
                        match_basis = "venue_name_token_and_city"
                if not match_basis:
                    continue

                drift = None
                if target["lng"] is not None and target["lat"] is not None and source_lng is not None and source_lat is not None:
                    drift = meters_between(target["lng"], target["lat"], source_lng, source_lat)
                strong = (
                    match_basis in {"address_normalized_exact", "address_mentioned_in_source_text"}
                    and bool(first(source_row.get("source_url")))
                    and source_lng is not None
                    and source_lat is not None
                    and drift is not None
                    and drift <= TAXI_GRADE_DRIFT_METERS
                )
                status = "strong_source_pack_candidate" if strong else "review_source_pack_candidate"
                hits[target["venue_id"]].append(short_source_hit(source_row, match_basis=match_basis, drift_meters=drift, status=status))
    return hits


def task_problem_class(row: dict[str, Any]) -> str:
    reasons = set(row.get("blocking_reasons") or [])
    if "current_source_address_conflict" in reasons:
        return "current_source_address_conflict"
    if "current_source_address_differs_from_registry" in reasons:
        return "current_source_address_differs_from_registry"
    if "no_current_release_item_for_venue" in reasons:
        return "no_current_release_item_for_venue"
    if "no_fresh_source_bound_current_item" in reasons:
        return "no_fresh_source_bound_current_item"
    return "other_blocked_latest_claim"


def acquisition_weapons(problem_class: str) -> list[dict[str, Any]]:
    base = [
        {
            "order": 1,
            "lane": "local_source_pack",
            "tool": "weekly_activity_expanded_pack_scan",
            "mode": "read_only",
            "purpose": "Find fresh source-bound official article rows with same venue address and taxi-grade coordinate.",
        },
        {
            "order": 2,
            "lane": "openclaw_incremental_download",
            "tool": "Docker exporter / OpenClaw incremental package",
            "mode": "bounded_fetch_after_auth_gate",
            "purpose": "Fetch or refresh official account current-window articles for the venue; retain raw-local evidence only until source acceptance.",
        },
    ]
    if problem_class in {"current_source_address_conflict", "current_source_address_differs_from_registry"}:
        base.append(
            {
                "order": 3,
                "lane": "provider_crosscheck",
                "tool": "Tencent/Amap provider probe through S132/S136 redacted gate",
                "mode": "bounded_provider_probe",
                "purpose": "Resolve address conflict by checking same city, same POI/street, coordinate drift, and provider auth status.",
            }
        )
    else:
        base.append(
            {
                "order": 3,
                "lane": "provider_crosscheck",
                "tool": "Tencent/Amap provider probe through S132/S136 redacted gate",
                "mode": "only_if_source_pack_and_current_source_do_not_resolve",
                "purpose": "Backstop only after official source search fails; redact auth and never write provider secrets.",
            }
        )
    base.append(
        {
            "order": 4,
            "lane": "db2_external_link_context",
            "tool": "db2ctl / Docker Compose profiles / external-link-db2-arsenal",
            "mode": "read_only_or_spool_dry_run",
            "purpose": "Use only if venue source acquisition needs public external-link context; writes must go through JSONL spool and db2-writer gates.",
        }
    )
    return base


def db2_control_surface() -> dict[str, Any]:
    return {
        "architecture": "Docker resident layered weapons runtime plus skill control plane",
        "not_allowed_interpretation": "one skill running every crawler/downloader/writer script directly",
        "module_log": str(MODULE_LOG),
        "weapon_catalog": WEAPON_CATALOG,
        "external_link_db2_arsenal_skill": str(ARSENAL_SKILL),
        "worktree": str(DB2_WEAPONS_WORKTREE),
        "db2ctl": str(DB2CTL_PATH),
        "compose": str(DB2_COMPOSE_PATH),
        "readme": str(DB2_WEAPONS_README),
        "read_only_checks": [
            "python tools/stage7_rewrite/scripts/db2ctl.py status",
            "python tools/stage7_rewrite/scripts/db2ctl.py health --lock-holders",
            "python tools/stage7_rewrite/scripts/db2ctl.py existing-data --limit 100",
            "python tools/stage7_rewrite/scripts/db2ctl.py cache status",
        ],
        "dry_run_worker_examples": [
            "python tools/stage7_rewrite/scripts/db2ctl.py up safe --worker outlink_expand_linktree",
            "python tools/stage7_rewrite/scripts/db2ctl.py up safe --worker outlink_expand_shorturl",
            "python tools/stage7_rewrite/scripts/db2ctl.py up safe --worker avatar_dl",
        ],
        "single_writer_gate": [
            "worker containers mount DB2 read-only",
            "worker write intent goes to /home/pc/swarm_data/write_spool JSONL",
            "only db2-writer may mount live DB2 read-write",
            "DB2_WRITER_EXECUTE remains off until explicit writer gate and readback pass",
        ],
        "skillopt_policy": [
            "skillopt-train-codex-oauth and skillopt-eval-codex-oauth are allowed only after eval cases, safety boundaries, and expected outputs exist",
            "SkillOpt is for skill/control-plane improvement, not direct production DB writes",
        ],
        "present": {
            "db2_worktree": DB2_WEAPONS_WORKTREE.exists(),
            "db2ctl": DB2CTL_PATH.exists(),
            "compose": DB2_COMPOSE_PATH.exists(),
            "module_log": MODULE_LOG.exists(),
            "arsenal_skill": ARSENAL_SKILL.exists(),
        },
    }


def build_task(row: dict[str, Any], source_hits: list[dict[str, Any]]) -> dict[str, Any]:
    strong_hits = [hit for hit in source_hits if hit["status"] == "strong_source_pack_candidate"]
    review_hits = [hit for hit in source_hits if hit["status"] == "review_source_pack_candidate"]
    problem_class = task_problem_class(row)
    if strong_hits:
        status = "ready_for_s136_source_acceptance_gate"
        next_action = "run bounded source-acceptance/write-gate script for this venue; do not write until S132/S136 backup lock readback controls pass"
    elif review_hits:
        status = "needs_source_review_before_write_gate"
        next_action = "review source-pack candidates for address/coordinate agreement, then promote only strong evidence into S136 source acceptance"
    else:
        status = "needs_external_source_or_provider_acquisition"
        next_action = "fetch current official source evidence or provider crosscheck through bounded Docker/OpenClaw/provider lane"

    return {
        "task_id": f"s136_acquisition:{row['venue_id']}",
        "venue_id": row["venue_id"],
        "canonical_name": row.get("canonical_name", ""),
        "city": row.get("city", ""),
        "problem_class": problem_class,
        "status": status,
        "write_allowed_now": False,
        "blocking_reasons": row.get("blocking_reasons", []),
        "current_item_count": row.get("current_item_count", 0),
        "source_bound_current_item_count": row.get("source_bound_current_item_count", 0),
        "registry": {
            "address": row.get("registry_address", ""),
            "geo_lng": row.get("registry_geo_lng"),
            "geo_lat": row.get("registry_geo_lat"),
            "geo_source": row.get("registry_geo_source", ""),
            "previous_last_verified_at": row.get("previous_last_verified_at", ""),
        },
        "current_source_items_sample": row.get("current_source_items", [])[:3],
        "local_source_pack": {
            "strong_candidate_count": len(strong_hits),
            "review_candidate_count": len(review_hits),
            "hits": source_hits[:8],
        },
        "allowed_weapon_chain": acquisition_weapons(problem_class),
        "requirements_before_any_write": [
            "fresh_after_2026_05_22_source_or_provider_evidence",
            "official_source_or_provider_result_bound_to_same_venue",
            "same_normalized_address_or_explicit_address_conflict_resolution",
            "coordinate_present_and_drift_lte_120m",
            "S132 backup lock readback rollback controls",
            "write only last_verified_at and source_note unless a later PRD authorizes more fields",
            "no DB1 DB2 DB3 SQLite projection from this queue alone",
            "no cookie token or secret values in reports or chat",
        ],
        "rollback_selector": row.get("rollback_selector", {"venue_id": row["venue_id"], "path": "$.venues[*]"}),
        "next_action": next_action,
    }


def render_scorecard(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Weekly Stale Registry Source Acquisition Queue S136",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Blocked S136 rows converted to tasks: `{summary['task_count']}`",
        f"- Ready for source-acceptance gate: `{summary['ready_for_source_acceptance_gate']}`",
        f"- Need source review: `{summary['needs_source_review']}`",
        f"- Need external/source provider acquisition: `{summary['needs_external_acquisition']}`",
        f"- Skipped already fresh in current registry: `{summary.get('skipped_already_fresh', 0)}`",
        f"- Strong local source-pack hits: `{summary['strong_source_pack_hit_count']}`",
        f"- Review local source-pack hits: `{summary['review_source_pack_hit_count']}`",
        f"- Finding count: `{report['finding_count']}`",
        "",
        "## DB2 / External-Link Control Surface",
        "",
        "- External-link work must route through Docker resident weapons plus `db2ctl`/profile gates and `external-link-db2-arsenal`; this queue does not authorize a single skill to run every script directly.",
        "- DB2 writes, if later authorized, must go through JSONL spool and the single `db2-writer` gate; this S136 queue itself is no-write.",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in sorted(summary["status_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Boundary", ""])
    lines.append(
        "- No registry mutation, no DB1/DB2/DB3/SQLite mutation, no release JSON write, no deploy/upload/review, no external crawl, no provider call, no model call, no cookie/token value read."
    )
    lines.extend(["", "## Next", ""])
    if summary["ready_for_source_acceptance_gate"]:
        lines.append("- Run a bounded source-acceptance/write-gate slice for the ready rows first, with S132/S136 backup, file lock, atomic write, and readback.")
    if summary["needs_external_acquisition"]:
        lines.append("- For the remaining rows, start with local/OpenClaw current-source acquisition; only use DB2 Docker weapons for public external-link context through `db2ctl` dry-run/profile gates.")
    return "\n".join(lines) + "\n"


def build_report(
    *,
    s136_report_path: Path,
    s136_rows_path: Path,
    source_pack_path: Path,
    registry_path: Path | None,
    out_dir: Path,
    scorecard_path: Path,
    fresh_after: str,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    s136_report = read_json(s136_report_path)
    s136_rows = read_jsonl(s136_rows_path)
    blocked_rows_all = [row for row in s136_rows if not row.get("write_ready")]
    blocked_rows, skipped_already_fresh = filter_currently_stale_rows(
        blocked_rows_all,
        registry_path=registry_path,
        fresh_after=fresh_after,
    )
    source_hits = load_source_pack_candidates(source_pack_path, blocked_rows, fresh_after=fresh_after)
    tasks = [build_task(row, source_hits.get(row["venue_id"], [])) for row in blocked_rows]

    status_counts = Counter(task["status"] for task in tasks)
    problem_counts = Counter(task["problem_class"] for task in tasks)
    strong_hits = sum(task["local_source_pack"]["strong_candidate_count"] for task in tasks)
    review_hits = sum(task["local_source_pack"]["review_candidate_count"] for task in tasks)
    findings: list[dict[str, Any]] = []
    expected_blocked = int((s136_report.get("summary") or {}).get("blocked_count") or 0)
    if expected_blocked != len(blocked_rows_all):
        findings.append(
            {
                "finding": "s136_blocked_count_mismatch",
                "expected_from_s136_report": expected_blocked,
                "actual_from_rows": len(blocked_rows_all),
            }
        )

    if strong_hits:
        decision = "stale_registry_source_acquisition_queue_ready_with_local_source_candidates"
    elif review_hits:
        decision = "stale_registry_source_acquisition_queue_ready_with_review_candidates"
    else:
        decision = "stale_registry_source_acquisition_queue_requires_external_acquisition"

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_cst(),
        "decision": decision,
        "inputs": {
            "s136_report": rel_path(s136_report_path),
            "s136_rows": rel_path(s136_rows_path),
            "source_pack": rel_path(source_pack_path),
            "registry": rel_path(registry_path) if registry_path else "",
        },
        "outputs": {
            "report": rel_path(out_dir / "stale_registry_source_acquisition_queue_s136.json"),
            "tasks": rel_path(out_dir / "stale_registry_source_acquisition_tasks_s136.jsonl"),
            "scorecard": rel_path(scorecard_path),
        },
        "freshness_policy": {
            "fresh_after": fresh_after,
            "taxi_grade_drift_meters": TAXI_GRADE_DRIFT_METERS,
        },
        "summary": {
            "task_count": len(tasks),
            "skipped_already_fresh": len(skipped_already_fresh),
            "ready_for_source_acceptance_gate": status_counts.get("ready_for_s136_source_acceptance_gate", 0),
            "needs_source_review": status_counts.get("needs_source_review_before_write_gate", 0),
            "needs_external_acquisition": status_counts.get("needs_external_source_or_provider_acquisition", 0),
            "strong_source_pack_hit_count": strong_hits,
            "review_source_pack_hit_count": review_hits,
            "status_counts": dict(status_counts),
            "problem_class_counts": dict(problem_counts),
        },
        "skipped_already_fresh": skipped_already_fresh,
        "db2_control_surface": db2_control_surface(),
        "boundary": {
            "report_only": True,
            "registry_mutation": False,
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
            "run S136 source-acceptance gate for local strong candidates"
            if strong_hits
            else "run bounded OpenClaw/source acquisition for remaining stale registry rows"
        ),
        "findings": findings,
        "finding_count": len(findings),
    }
    write_json(out_dir / "stale_registry_source_acquisition_queue_s136.json", report)
    write_jsonl(out_dir / "stale_registry_source_acquisition_tasks_s136.jsonl", tasks)
    write_text_atomic(scorecard_path, render_scorecard(report))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s136-report", type=Path, default=DEFAULT_S136_REPORT)
    parser.add_argument("--s136-rows", type=Path, default=DEFAULT_S136_ROWS)
    parser.add_argument("--source-pack", type=Path, default=DEFAULT_SOURCE_PACK)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--fresh-after", default=DEFAULT_FRESH_AFTER)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(
        s136_report_path=args.s136_report,
        s136_rows_path=args.s136_rows,
        source_pack_path=args.source_pack,
        registry_path=args.registry,
        out_dir=args.out_dir,
        scorecard_path=args.scorecard,
        fresh_after=args.fresh_after,
    )
    print(json.dumps({"decision": report["decision"], "summary": report["summary"]}, ensure_ascii=False, sort_keys=True))
    return 0 if report["finding_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
