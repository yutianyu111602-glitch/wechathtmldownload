#!/usr/bin/env python3
"""Refresh the DB3 relation-identity queue after the S148 canary.

S149 is read-only. It proves the S148 old id is absent from live DB3 surfaces,
rescans current compact identity-token groups from DB3, recomputes live impact
metrics for the remaining S146 candidates, excludes S145 evidence gaps, and
selects the next bounded canary candidate for a later write gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S149"
SCHEMA_VERSION = "atlas_relation_identity_post_canary_refresh_s149.v1"

DEFAULT_S148_REPORT = (
    REPORTS_ROOT
    / "atlas_relation_identity_db3_canary_s148_20260602"
    / "atlas_relation_identity_db3_canary_s148.json"
)
DEFAULT_S146_ROWS = (
    REPORTS_ROOT
    / "atlas_relation_identity_db3_prewrite_dryrun_s146_20260602"
    / "relation_identity_db3_prewrite_rows_s146.jsonl"
)
DEFAULT_S146_GAPS = (
    REPORTS_ROOT
    / "atlas_relation_identity_db3_prewrite_dryrun_s146_20260602"
    / "relation_identity_db3_prewrite_gap_rows_s146.jsonl"
)
DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_post_canary_refresh_s149_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_POST_CANARY_REFRESH_S149_20260602.md"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object JSON: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def connect_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def normalized_token(value: Any) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").strip().lower())


def parse_aliases(value: Any) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return [str(value).strip()] if str(value).strip() else []
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return []


def placeholders(values: list[str]) -> str:
    return ",".join("?" for _ in values)


def count_table(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] or 0)


def count_in(conn: sqlite3.Connection, table: str, field: str, values: list[str]) -> int:
    if not values:
        return 0
    return int(
        conn.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE "{field}" IN ({placeholders(values)})',
            tuple(values),
        ).fetchone()[0]
        or 0
    )


def count_collaborators(conn: sqlite3.Connection, values: list[str]) -> int:
    if not values:
        return 0
    marks = placeholders(values)
    return int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM dj_collaborator
            WHERE src_dj_id IN ({marks}) OR dst_dj_id IN ({marks})
            """,
            tuple(values + values),
        ).fetchone()[0]
        or 0
    )


def count_distinct_source_refs(conn: sqlite3.Connection, values: list[str]) -> int:
    if not values:
        return 0
    marks = placeholders(values)
    return int(
        conn.execute(
            f"""
            SELECT COUNT(DISTINCT e.source_ref_id)
            FROM dj_event e
            JOIN source_ref s ON s.source_ref_id = e.source_ref_id
            WHERE e.dj_id IN ({marks})
              AND e.source_ref_id IS NOT NULL
              AND e.source_ref_id != ''
            """,
            tuple(values),
        ).fetchone()[0]
        or 0
    )


def count_broken_source_refs(conn: sqlite3.Connection, values: list[str]) -> int:
    if not values:
        return 0
    marks = placeholders(values)
    return int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM dj_event e
            LEFT JOIN source_ref s ON s.source_ref_id = e.source_ref_id
            WHERE e.dj_id IN ({marks})
              AND e.source_ref_id IS NOT NULL
              AND e.source_ref_id != ''
              AND s.source_ref_id IS NULL
            """,
            tuple(values),
        ).fetchone()[0]
        or 0
    )


def collision_count(conn: sqlite3.Connection, table: str, id_col: str, key_col: str, canonical: str, old_ids: list[str]) -> int:
    if not old_ids:
        return 0
    all_ids = [canonical, *old_ids]
    marks = placeholders(all_ids)
    return int(
        conn.execute(
            f"""
            SELECT COUNT(*) - COUNT(DISTINCT {key_col})
            FROM {table}
            WHERE {id_col} IN ({marks})
            """,
            tuple(all_ids),
        ).fetchone()[0]
        or 0
    )


def collaborator_self_loops_after_redirect(conn: sqlite3.Connection, canonical: str, old_ids: list[str]) -> int:
    all_ids = [canonical, *old_ids]
    if not all_ids:
        return 0
    marks = placeholders(all_ids)
    rows = conn.execute(
        f"""
        SELECT src_dj_id, dst_dj_id
        FROM dj_collaborator
        WHERE src_dj_id IN ({marks}) OR dst_dj_id IN ({marks})
        """,
        tuple(all_ids + all_ids),
    ).fetchall()
    old_set = set(old_ids)
    loops = 0
    for row in rows:
        src = canonical if row["src_dj_id"] in old_set else str(row["src_dj_id"])
        dst = canonical if row["dst_dj_id"] in old_set else str(row["dst_dj_id"])
        if src == dst:
            loops += 1
    return loops


def profile_row(conn: sqlite3.Connection, dj_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT dj_id, display_name, normalized_name, aliases_json, city_primary,
               event_count, venue_count, collaborator_count, bio_source
        FROM dj_profile
        WHERE dj_id = ?
        """,
        (dj_id,),
    ).fetchone()
    return dict(row) if row else None


def scan_identity_token_groups(conn: sqlite3.Connection, *, limit: int = 80) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT dj_id, display_name, normalized_name, aliases_json, city_primary
        FROM dj_profile
        WHERE COALESCE(dj_id, '') <> ''
        """
    ).fetchall()
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    empty_normalized = 0
    empty_sample: list[dict[str, str]] = []
    for row in rows:
        dj_id = str(row["dj_id"])
        display = str(row["display_name"] or "").strip()
        normalized_name = str(row["normalized_name"] or "")
        city = str(row["city_primary"] or "")
        city_token = normalized_token(city)
        normalized = normalized_token(normalized_name)
        if not normalized:
            empty_normalized += 1
            if len(empty_sample) < limit:
                empty_sample.append(
                    {
                        "dj_id": dj_id,
                        "display_name": display,
                        "normalized_name": normalized_name,
                        "city_primary": city,
                    }
                )
        tokens = {normalized, normalized_token(display)}
        tokens.update(normalized_token(alias) for alias in parse_aliases(row["aliases_json"]))
        for token in {token for token in tokens if len(token) >= 2}:
            groups[(city_token, token)].append(
                {
                    "dj_id": dj_id,
                    "display_name": display,
                    "normalized_name": normalized_name,
                    "city_primary": city,
                }
            )
    exact_groups: list[dict[str, Any]] = []
    alias_groups: list[dict[str, Any]] = []
    group_by_key: dict[str, dict[str, Any]] = {}
    for (city_token, token), members in sorted(groups.items()):
        ids = sorted({member["dj_id"] for member in members})
        if len(ids) <= 1:
            continue
        normalized_values = sorted({normalized_token(member["normalized_name"]) for member in members if member["normalized_name"]})
        names = sorted({member["display_name"] for member in members if member["display_name"]})
        city_values = sorted({member["city_primary"] for member in members if member["city_primary"]})
        city_label = city_values[0] if len(city_values) == 1 else city_token
        payload = {
            "city_key": city_label,
            "city_token": city_token,
            "identity_token": token,
            "group_id": f"{city_label}::{token}",
            "dj_ids": ids,
            "display_names": names[:12],
            "normalized_names": normalized_values[:12],
            "row_count": len(members),
        }
        group_by_key[f"{city_token}::{token}"] = payload
        if len(normalized_values) == 1 and normalized_values[0] == token:
            exact_groups.append(payload)
        else:
            alias_groups.append(payload)
    return {
        "profile_rows": len(rows),
        "empty_normalized_profile_count": empty_normalized,
        "compact_token_multi_id_group_count": len(exact_groups) + len(alias_groups),
        "same_normalized_multi_id_group_count": len(exact_groups),
        "alias_token_multi_id_group_count": len(alias_groups),
        "empty_normalized_profile_sample": empty_sample,
        "same_normalized_multi_id_sample": exact_groups[:limit],
        "alias_token_multi_id_sample": alias_groups[:limit],
        "group_by_key": group_by_key,
    }


def group_token_from_id(group_id: str) -> tuple[str, str]:
    city, _, token = str(group_id or "").partition("::")
    return normalized_token(city), normalized_token(token)


def old_id_surface_counts(conn: sqlite3.Connection, old_ids: list[str]) -> dict[str, int]:
    return {
        "dj_profile": count_in(conn, "dj_profile", "dj_id", old_ids),
        "subject": count_in(conn, "subject", "subject_id", old_ids),
        "dj_event": count_in(conn, "dj_event", "dj_id", old_ids),
        "dj_venue": count_in(conn, "dj_venue", "dj_id", old_ids),
        "dj_collaborator": count_collaborators(conn, old_ids),
    }


def prove_s148_closure(conn: sqlite3.Connection, s148_report: dict[str, Any], identity_scan: dict[str, Any]) -> dict[str, Any]:
    selected = s148_report.get("selected_canary") if isinstance(s148_report.get("selected_canary"), dict) else {}
    canonical = str(selected.get("canonical_dj_id") or "")
    old_ids = [str(value) for value in selected.get("merge_dj_ids") or [] if str(value)]
    city_token, token = group_token_from_id(str(selected.get("group_id") or ""))
    closure_group = (identity_scan.get("group_by_key") or {}).get(f"{city_token}::{token}")
    surface_counts = old_id_surface_counts(conn, old_ids)
    canonical = str(selected.get("canonical_dj_id") or "")
    canonical_profile = profile_row(conn, canonical) if canonical else None
    old_absent = all(value == 0 for value in surface_counts.values())
    group_multi_absent = closure_group is None
    if closure_group:
        group_ids = set(closure_group.get("dj_ids") or [])
        group_multi_absent = len(group_ids) <= 1 and not any(old_id in group_ids for old_id in old_ids)
    ok = bool(
        s148_report.get("decision") == "atlas_relation_identity_db3_canary_s148_committed_with_readback"
        and ((s148_report.get("write_state") or {}).get("committed") is True)
        and old_absent
        and canonical_profile
        and group_multi_absent
    )
    return {
        "ok": ok,
        "s148_decision": s148_report.get("decision"),
        "s148_committed": bool((s148_report.get("write_state") or {}).get("committed")),
        "selected_group_id": selected.get("group_id"),
        "selected_prewrite_row_id": selected.get("prewrite_row_id"),
        "canonical_dj_id": canonical,
        "merge_dj_ids": old_ids,
        "old_id_surface_counts": surface_counts,
        "old_id_absent_from_all_surfaces": old_absent,
        "canonical_profile_present": bool(canonical_profile),
        "canonical_profile": canonical_profile or {},
        "closure_identity_token": token,
        "closure_city_token": city_token,
        "closure_multi_id_group_present": bool(closure_group),
        "closure_multi_id_group": closure_group or {},
        "shanghai_bo_closed": ok if selected.get("group_id") == "上海::bo" else group_multi_absent,
    }


def live_row_estimate(conn: sqlite3.Connection, row: dict[str, Any]) -> dict[str, Any]:
    canonical = str(row.get("canonical_dj_id") or "")
    merge_ids = [str(value) for value in row.get("merge_dj_ids") or [] if str(value)]
    all_ids = [str(value) for value in row.get("all_dj_ids") or [] if str(value)] or [canonical, *merge_ids]
    return {
        "canonical_current_rows": {
            "dj_profile": count_in(conn, "dj_profile", "dj_id", [canonical]),
            "subject": count_in(conn, "subject", "subject_id", [canonical]),
            "dj_event": count_in(conn, "dj_event", "dj_id", [canonical]),
            "dj_venue": count_in(conn, "dj_venue", "dj_id", [canonical]),
            "dj_collaborator": count_collaborators(conn, [canonical]),
            "source_ref_readback_only": count_distinct_source_refs(conn, [canonical]),
        },
        "merge_rows_to_redirect": {
            "dj_profile": count_in(conn, "dj_profile", "dj_id", merge_ids),
            "subject": count_in(conn, "subject", "subject_id", merge_ids),
            "dj_event": count_in(conn, "dj_event", "dj_id", merge_ids),
            "dj_venue": count_in(conn, "dj_venue", "dj_id", merge_ids),
            "dj_collaborator": count_collaborators(conn, merge_ids),
            "source_ref_readback_only": count_distinct_source_refs(conn, merge_ids),
        },
        "all_identity_rows_for_readback": {
            "dj_profile": count_in(conn, "dj_profile", "dj_id", all_ids),
            "subject": count_in(conn, "subject", "subject_id", all_ids),
            "dj_event": count_in(conn, "dj_event", "dj_id", all_ids),
            "dj_venue": count_in(conn, "dj_venue", "dj_id", all_ids),
            "dj_collaborator": count_collaborators(conn, all_ids),
            "source_ref_readback_only": count_distinct_source_refs(conn, all_ids),
        },
        "dedupe_risk_estimate": {
            "source_ref_integrity_breaks_before_write": count_broken_source_refs(conn, all_ids),
            "event_collision_groups_after_redirect": collision_count(conn, "dj_event", "dj_id", "event_id", canonical, merge_ids),
            "venue_collision_groups_after_redirect": collision_count(conn, "dj_venue", "dj_id", "venue_id", canonical, merge_ids),
            "collaborator_self_loops_after_redirect": collaborator_self_loops_after_redirect(conn, canonical, merge_ids),
        },
    }


def redirect_total(row: dict[str, Any]) -> int:
    estimate = row.get("live_affected_row_estimate") or row.get("affected_row_estimate") or {}
    values = estimate.get("merge_rows_to_redirect") if isinstance(estimate, dict) else {}
    if not isinstance(values, dict):
        return 0
    return sum(int(value or 0) for value in values.values())


def risk_tuple(row: dict[str, Any]) -> tuple[int, int, int, int, int, int, str, str]:
    estimate = row.get("live_affected_row_estimate") or {}
    risk = estimate.get("dedupe_risk_estimate") if isinstance(estimate, dict) else {}
    if not isinstance(risk, dict):
        risk = {}
    return (
        redirect_total(row),
        int(risk.get("source_ref_integrity_breaks_before_write") or 0),
        int(risk.get("event_collision_groups_after_redirect") or 0),
        int(risk.get("venue_collision_groups_after_redirect") or 0),
        int(risk.get("collaborator_self_loops_after_redirect") or 0),
        len(row.get("merge_dj_ids") or []),
        str(row.get("group_id") or ""),
        str(row.get("prewrite_row_id") or ""),
    )


def refresh_candidate_row(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    *,
    executed_prewrite_ids: set[str],
    gap_group_ids: set[str],
    gap_dj_ids: set[str],
    identity_scan: dict[str, Any],
) -> dict[str, Any]:
    canonical = str(row.get("canonical_dj_id") or "")
    merge_ids = [str(value) for value in row.get("merge_dj_ids") or [] if str(value)]
    all_ids = [str(value) for value in row.get("all_dj_ids") or [] if str(value)] or [canonical, *merge_ids]
    live_estimate = live_row_estimate(conn, row)
    city_token, token = group_token_from_id(str(row.get("group_id") or ""))
    live_group = (identity_scan.get("group_by_key") or {}).get(f"{city_token}::{token}") or {}
    canonical_present = bool(profile_row(conn, canonical))
    merge_present = [dj_id for dj_id in merge_ids if profile_row(conn, dj_id)]
    merge_absent = [dj_id for dj_id in merge_ids if dj_id not in set(merge_present)]
    source_ref_breaks = int((live_estimate.get("dedupe_risk_estimate") or {}).get("source_ref_integrity_breaks_before_write") or 0)
    dryrun_pass = bool(((row.get("field_preservation") or {}).get("no_empty_overwrite_assertions") or {}).get("dryrun_pass"))
    source_ref_coverage_complete = bool((row.get("candidate_source") or {}).get("source_ref_coverage_complete"))
    exclusion_reasons: list[str] = []
    if row.get("prewrite_row_id") in executed_prewrite_ids:
        exclusion_reasons.append("already_executed_s148_canary")
    if row.get("group_id") in gap_group_ids or any(dj_id in gap_dj_ids for dj_id in all_ids):
        exclusion_reasons.append("excluded_s145_evidence_gap")
    if not canonical_present:
        exclusion_reasons.append("canonical_profile_missing_live_db3")
    if merge_absent:
        exclusion_reasons.append("merge_profile_missing_live_db3")
    if source_ref_breaks:
        exclusion_reasons.append("source_ref_integrity_breaks_live_db3")
    if not dryrun_pass:
        exclusion_reasons.append("s146_no_empty_overwrite_dryrun_not_passed")
    if not source_ref_coverage_complete:
        exclusion_reasons.append("s146_source_ref_coverage_incomplete")
    can_feed = not exclusion_reasons
    refreshed = {
        "s149_queue_row_id": f"s149:{stable_id([row.get('prewrite_row_id'), live_estimate])}",
        "source_prewrite_row_id": row.get("prewrite_row_id"),
        "group_id": row.get("group_id"),
        "city_key": row.get("city_key"),
        "display_names": row.get("display_names") or [],
        "canonical_dj_id": canonical,
        "merge_dj_ids": merge_ids,
        "all_dj_ids": all_ids,
        "live_profile_presence": {
            "canonical_present": canonical_present,
            "merge_present_ids": merge_present,
            "merge_absent_ids": merge_absent,
        },
        "live_identity_token_group": live_group,
        "live_affected_row_estimate": live_estimate,
        "risk_tuple_live": list(risk_tuple({"live_affected_row_estimate": live_estimate, **row})),
        "can_feed_next_execution_gate": can_feed,
        "exclusion_reasons": exclusion_reasons,
        "s145_gap_excluded": "excluded_s145_evidence_gap" in exclusion_reasons,
        "s148_executed_excluded": "already_executed_s148_canary" in exclusion_reasons,
        "report_only": True,
        "database_write_allowed": False,
        "db3_mutation": False,
        "source_ref_preservation": row.get("source_ref_preservation") or {},
        "field_preservation": row.get("field_preservation") or {},
        "postwrite_readback_selectors": row.get("postwrite_readback_selectors") or {},
        "rollback_selector": row.get("rollback_selector") or {},
    }
    return refreshed


def build_tasks(report: dict[str, Any]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    next_canary = report.get("next_canary") if isinstance(report.get("next_canary"), dict) else {}
    if report.get("s148_closure", {}).get("ok") is not True:
        tasks.append(
            {
                "story_id": CURRENT_STORY_ID,
                "task_id": "s149:s148_closure_failed",
                "status": "blocked",
                "next_action": "Audit the S148 canary readback before selecting any further DB3 identity write.",
            }
        )
    if next_canary:
        tasks.append(
            {
                "story_id": CURRENT_STORY_ID,
                "task_id": "s149:next_canary_gate_ready_report_only",
                "status": "next",
                "group_id": next_canary.get("group_id"),
                "source_prewrite_row_id": next_canary.get("source_prewrite_row_id"),
                "next_action": "Build S150 single-row operator approval/execution gate from this refreshed live queue row; do not write until approval, lock, backup, rollback, and readback bind to the live metrics.",
            }
        )
    else:
        tasks.append(
            {
                "story_id": CURRENT_STORY_ID,
                "task_id": "s149:no_next_canary",
                "status": "blocked",
                "next_action": "Repair excluded rows or collect more source evidence before any further DB3 identity write.",
            }
        )
    if report.get("candidate_refresh_counts", {}).get("s145_gap_row_count"):
        tasks.append(
            {
                "story_id": CURRENT_STORY_ID,
                "task_id": "s149:s145_gap_rows_still_blocked",
                "status": "blocked",
                "blocked_count": report["candidate_refresh_counts"]["s145_gap_row_count"],
                "next_action": "Keep S145 gap rows out of write execution until missing collaborator/venue evidence is collected.",
            }
        )
    tasks.append(
        {
            "story_id": CURRENT_STORY_ID,
            "task_id": "s149:preserve_other_blockers",
            "status": "carry_forward",
            "next_action": "DB2 projection, release rebuild, deploy, upload, review, rendered DevTools coverage, and S136 source/provider evidence remain separate blockers.",
        }
    )
    return tasks


def carry_forward_gap_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "s149_excluded_row_id": f"s149-gap:{stable_id(row)}",
        "source": "s145_gap_row_carried_forward_via_s146",
        "group_id": row.get("group_id"),
        "canonical_dj_id": row.get("canonical_dj_id"),
        "merge_dj_ids": row.get("merge_dj_ids") or [],
        "all_dj_ids": row.get("all_dj_ids") or [],
        "display_names": row.get("display_names") or [],
        "gap_codes": row.get("gap_codes") or [],
        "status": "blocked_evidence_gap",
        "can_feed_next_execution_gate": False,
        "database_write_allowed": False,
        "db3_mutation": False,
        "exclusion_reasons": ["s145_evidence_gap_carried_forward"],
        "next_action": "Collect missing collaborator/venue/source evidence before any DB3 identity write gate.",
    }


def build_report(
    *,
    s148_report_path: Path,
    s146_rows_path: Path,
    s146_gaps_path: Path,
    db3_path: Path,
    out_dir: Path,
    queue_limit: int,
) -> dict[str, Any]:
    s148_report = read_json(s148_report_path)
    s146_rows = read_jsonl(s146_rows_path)
    gap_rows = read_jsonl(s146_gaps_path)
    executed_prewrite_ids = {
        str((s148_report.get("selected_canary") or {}).get("prewrite_row_id") or "")
    } - {""}
    gap_group_ids = {str(row.get("group_id") or "") for row in gap_rows if row.get("group_id")}
    gap_dj_ids = {
        str(value)
        for row in gap_rows
        for value in (row.get("all_dj_ids") or [row.get("canonical_dj_id"), *(row.get("merge_dj_ids") or [])])
        if str(value)
    }
    gap_carry_rows = [carry_forward_gap_row(row) for row in gap_rows]
    conn = connect_ro(db3_path)
    try:
        identity_scan = scan_identity_token_groups(conn)
        s148_closure = prove_s148_closure(conn, s148_report, identity_scan)
        refreshed_rows = [
            refresh_candidate_row(
                conn,
                row,
                executed_prewrite_ids=executed_prewrite_ids,
                gap_group_ids=gap_group_ids,
                gap_dj_ids=gap_dj_ids,
                identity_scan=identity_scan,
            )
            for row in s146_rows
        ]
        table_counts = {
            table: count_table(conn, table)
            for table in ["dj_profile", "subject", "dj_event", "dj_venue", "dj_collaborator", "source_ref"]
        }
    finally:
        conn.close()
    eligible_rows = [row for row in refreshed_rows if row["can_feed_next_execution_gate"]]
    excluded_rows = [row for row in refreshed_rows if not row["can_feed_next_execution_gate"]]
    ranked_queue = sorted(eligible_rows, key=risk_tuple)
    next_canary = ranked_queue[0] if ranked_queue else None
    reason_counts = Counter(reason for row in excluded_rows for reason in row.get("exclusion_reasons", []))
    decision = (
        "atlas_relation_identity_post_canary_refresh_s149_ready_next_canary_report_only"
        if s148_closure["ok"] and next_canary
        else "atlas_relation_identity_post_canary_refresh_s149_blocked_report_only"
    )
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "current_story_id": CURRENT_STORY_ID,
        "generated_at": now_iso(),
        "decision": decision,
        "source_inputs": {
            "s148_report": rel_path(s148_report_path),
            "s148_report_sha256": sha256_file(s148_report_path),
            "s146_prewrite_rows": rel_path(s146_rows_path),
            "s146_prewrite_rows_sha256": sha256_file(s146_rows_path),
            "s146_gap_rows": rel_path(s146_gaps_path),
            "s146_gap_rows_sha256": sha256_file(s146_gaps_path),
            "db3": rel_path(db3_path),
        },
        "s148_closure": s148_closure,
        "live_db3_identity_state": {
            "table_counts": table_counts,
            "profile_rows": identity_scan["profile_rows"],
            "empty_normalized_profile_count": identity_scan["empty_normalized_profile_count"],
            "same_normalized_multi_id_group_count": identity_scan["same_normalized_multi_id_group_count"],
            "alias_token_multi_id_group_count": identity_scan["alias_token_multi_id_group_count"],
            "compact_token_multi_id_group_count": identity_scan["compact_token_multi_id_group_count"],
            "same_normalized_multi_id_sample": identity_scan["same_normalized_multi_id_sample"],
            "alias_token_multi_id_sample": identity_scan["alias_token_multi_id_sample"],
            "empty_normalized_profile_sample": identity_scan["empty_normalized_profile_sample"],
        },
        "candidate_refresh_counts": {
            "s146_input_count": len(s146_rows),
            "s145_gap_row_count": len(gap_rows),
            "s145_gap_rows_carried_forward_count": len(gap_carry_rows),
            "executed_prewrite_excluded_count": sum(1 for row in refreshed_rows if row["s148_executed_excluded"]),
            "excluded_s145_gap_count": sum(1 for row in refreshed_rows if row["s145_gap_excluded"]),
            "eligible_next_canary_count": len(eligible_rows),
            "excluded_candidate_count": len(excluded_rows),
            "exclusion_reason_counts": dict(sorted(reason_counts.items())),
        },
        "next_canary": next_canary or {},
        "next_canary_queue_count": len(ranked_queue),
        "next_canary_queue_sample": ranked_queue[: min(queue_limit, len(ranked_queue))],
        "excluded_candidate_sample": excluded_rows[: min(queue_limit, len(excluded_rows))],
        "s145_gap_rows_carried_forward": gap_carry_rows,
        "production_state": {
            "read_only_selector": True,
            "database_mutations": False,
            "db3_identity_write": False,
            "db2_projection": False,
            "release_rebuild": False,
            "deploy": False,
            "upload": False,
            "review": False,
            "raw_secret_values_printed": False,
        },
        "rules": [
            "S149 recomputes affected rows and risks from live DB3.",
            "S148 selected row and S145 gap rows are excluded from write execution.",
            "This packet is not an approval artifact and not a DB3 write gate.",
            "A later S150 gate must bind approval, single-writer lock, backup, rollback, postwrite readback, and no-empty-overwrite checks before any mutation.",
        ],
    }
    report["next_action_tasks"] = build_tasks(report)
    out_dir.mkdir(parents=True, exist_ok=True)
    return report


def render_markdown(report: dict[str, Any], paths: dict[str, str]) -> str:
    counts = report.get("candidate_refresh_counts") or {}
    state = report.get("live_db3_identity_state") or {}
    closure = report.get("s148_closure") or {}
    next_canary = report.get("next_canary") or {}
    lines = [
        "# Atlas Relation Identity Post-Canary Refresh S149",
        "",
        f"- Decision: `{report.get('decision')}`",
        f"- S148 closure ok: `{closure.get('ok')}`",
        f"- Selected S148 group closed: `{closure.get('selected_group_id')}`",
        f"- Old ID surface counts: `{closure.get('old_id_surface_counts')}`",
        f"- Live compact token multi-id groups: `{state.get('compact_token_multi_id_group_count')}`",
        f"- Live same-normalized multi-id groups: `{state.get('same_normalized_multi_id_group_count')}`",
        f"- Live alias-token multi-id groups: `{state.get('alias_token_multi_id_group_count')}`",
        f"- Empty normalized profiles: `{state.get('empty_normalized_profile_count')}`",
        f"- S146 rows / eligible queue / excluded: `{counts.get('s146_input_count')}` / `{counts.get('eligible_next_canary_count')}` / `{counts.get('excluded_candidate_count')}`",
        f"- S145 gap rows carried forward: `{counts.get('s145_gap_rows_carried_forward_count')}`",
        "",
        "## Next Canary",
        "",
    ]
    if next_canary:
        lines.extend(
            [
                f"- Group: `{next_canary.get('group_id')}`",
                f"- Source prewrite row: `{next_canary.get('source_prewrite_row_id')}`",
                f"- Canonical: `{next_canary.get('canonical_dj_id')}`",
                f"- Merge IDs: `{next_canary.get('merge_dj_ids')}`",
                f"- Live risk tuple: `{next_canary.get('risk_tuple_live')}`",
            ]
        )
    else:
        lines.append("- No next canary selected.")
    lines.extend(
        [
            "",
            "## Output Files",
            "",
            f"- JSON: `{paths['json']}`",
            f"- Queue: `{paths['queue']}`",
            f"- Excluded: `{paths['excluded']}`",
            f"- Tasks: `{paths['tasks']}`",
            "",
            "## Boundary",
            "",
            "- S149 is read-only and report-local.",
            "- No DB1/DB2/DB3 mutation, no DB2 projection, no release rebuild, no deploy/upload/review.",
            "- The next row still needs a separate operator approval and execution gate.",
            "",
        ]
    )
    return "\n".join(lines)


def render_scorecard(report: dict[str, Any], paths: dict[str, str]) -> str:
    markdown = render_markdown(report, paths)
    return markdown.replace("# Atlas Relation Identity Post-Canary Refresh S149", "# Atlas Relation Identity Post-Canary Refresh S149\n\nScorecard.")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s148-report", type=Path, default=DEFAULT_S148_REPORT)
    parser.add_argument("--s146-rows", type=Path, default=DEFAULT_S146_ROWS)
    parser.add_argument("--s146-gaps", type=Path, default=DEFAULT_S146_GAPS)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--queue-limit", type=int, default=20)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_report(
        s148_report_path=args.s148_report,
        s146_rows_path=args.s146_rows,
        s146_gaps_path=args.s146_gaps,
        db3_path=args.db3,
        out_dir=args.out_dir,
        queue_limit=args.queue_limit,
    )
    queue_rows = report["next_canary_queue_sample"] if args.queue_limit else []
    all_queue_rows = sorted(
        [
            row
            for row in report["next_canary_queue_sample"]
        ],
        key=risk_tuple,
    )
    # The report keeps a bounded sample; materialize the full queue by rebuilding
    # with an effectively unbounded limit when the default bounded sample clipped.
    if report["next_canary_queue_count"] > len(all_queue_rows):
        full_report = build_report(
            s148_report_path=args.s148_report,
            s146_rows_path=args.s146_rows,
            s146_gaps_path=args.s146_gaps,
            db3_path=args.db3,
            out_dir=args.out_dir,
            queue_limit=max(report["next_canary_queue_count"], args.queue_limit),
        )
        queue_rows = full_report["next_canary_queue_sample"]
    else:
        queue_rows = all_queue_rows
    paths = {
        "json": rel_path(args.out_dir / "atlas_relation_identity_post_canary_refresh_s149.json"),
        "queue": rel_path(args.out_dir / "relation_identity_next_canary_queue_s149.jsonl"),
        "excluded": rel_path(args.out_dir / "relation_identity_excluded_rows_s149.jsonl"),
        "tasks": rel_path(args.out_dir / "relation_identity_post_canary_tasks_s149.jsonl"),
        "markdown": rel_path(args.out_dir / "atlas_relation_identity_post_canary_refresh_s149.md"),
        "scorecard": rel_path(args.scorecard),
    }
    atomic_write_json(args.out_dir / "atlas_relation_identity_post_canary_refresh_s149.json", report)
    atomic_write_jsonl(args.out_dir / "relation_identity_next_canary_queue_s149.jsonl", queue_rows)
    atomic_write_jsonl(
        args.out_dir / "relation_identity_excluded_rows_s149.jsonl",
        report["excluded_candidate_sample"] + report["s145_gap_rows_carried_forward"],
    )
    atomic_write_jsonl(args.out_dir / "relation_identity_post_canary_tasks_s149.jsonl", report["next_action_tasks"])
    atomic_write_text(args.out_dir / "atlas_relation_identity_post_canary_refresh_s149.md", render_markdown(report, paths))
    atomic_write_text(args.scorecard, render_scorecard(report, paths))
    print(json.dumps({"decision": report["decision"], "s148_closure_ok": report["s148_closure"]["ok"], "next_canary": report["next_canary"].get("group_id")}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
