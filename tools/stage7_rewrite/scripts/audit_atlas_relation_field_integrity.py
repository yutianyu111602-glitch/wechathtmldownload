#!/usr/bin/env python3
"""Audit DB2/DB3 Atlas relation-field integrity.

Read-only guard for the user-reported failures: missing DJ-DJ links, missing
DJ/venue history, inconsistent ids, and empty fields overwriting richer
relation data. The script samples DB2 high-confidence relation rows, checks the
DB3 mini-program projection, and writes JSON/Markdown evidence only.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB2 = (
    REPO_ROOT
    / "reports"
    / "atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018"
    / "atlas_serving.sqlite"
)
DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_WEEKLY_CURRENT = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release" / "current.json"
DEFAULT_OUT_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "atlas_relation_field_integrity_20260531"
STAGE7_REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def connect_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    value = conn.execute(sql, params).fetchone()[0]
    return int(value or 0)


def table_count(conn: sqlite3.Connection, table: str) -> int:
    return scalar(conn, f'SELECT COUNT(*) FROM "{table}"')


def non_empty_count(conn: sqlite3.Connection, table: str, field: str) -> int:
    return scalar(conn, f'SELECT COUNT(*) FROM "{table}" WHERE COALESCE("{field}", \'\') <> \'\'')


def invalid_identity_count(conn: sqlite3.Connection, table: str, src_field: str, dst_field: str) -> int:
    return scalar(
        conn,
        f'''
        SELECT COUNT(*)
        FROM "{table}"
        WHERE COALESCE("{src_field}", '') = ''
           OR COALESCE("{dst_field}", '') = ''
           OR "{src_field}" = "{dst_field}"
        ''',
    )


def normalized_token(value: Any) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").strip().lower())


def parse_aliases(value: Any) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return []


def missing_fk_count(conn: sqlite3.Connection, table: str, field: str, ref_table: str, ref_field: str) -> int:
    return scalar(
        conn,
        f'''
        SELECT COUNT(*)
        FROM "{table}"
        WHERE COALESCE("{field}", '') <> ''
          AND "{field}" NOT IN (SELECT "{ref_field}" FROM "{ref_table}" WHERE COALESCE("{ref_field}", '') <> '')
        ''',
    )


def sample_db2_relations(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT src_dj_id, dst_dj_id, same_event_count, relation_score, relation_label_zh
        FROM dj_relation_rollup
        WHERE COALESCE(src_dj_id, '') <> ''
          AND COALESCE(dst_dj_id, '') <> ''
          AND src_dj_id <> dst_dj_id
        ORDER BY relation_score DESC, same_event_count DESC, src_dj_id, dst_dj_id
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "src_dj_id": row[0],
            "dst_dj_id": row[1],
            "same_event_count": int(row[2] or 0),
            "relation_score": float(row[3] or 0),
            "relation_label_zh": row[4] or "",
        }
        for row in rows
    ]


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def discover_identity_merge_reports() -> list[Path]:
    patterns = [
        "atlas_relation_identity_db3_canary_s*/atlas_relation_identity_db3_canary_s*.json",
        "atlas_relation_identity_db3_autobatch_s*/atlas_relation_identity_db3_autobatch_s156.json",
    ]
    paths: set[Path] = set()
    for pattern in patterns:
        paths.update(STAGE7_REPORTS_ROOT.glob(pattern))
    return sorted(paths)


def execution_committed(execution: dict[str, Any]) -> bool:
    return bool(execution.get("committed") and execution.get("write_executed"))


def add_redirect_row(
    rows: list[dict[str, str]],
    *,
    old_dj_id: Any,
    canonical_dj_id: Any,
    group_id: Any,
    source_story_id: Any,
    source_kind: str,
    report_path: Path | None = None,
) -> None:
    old = str(old_dj_id or "").strip()
    canonical = str(canonical_dj_id or "").strip()
    if not old or not canonical or old == canonical:
        return
    rows.append(
        {
            "old_dj_id": old,
            "canonical_dj_id": canonical,
            "group_id": str(group_id or ""),
            "source_story_id": str(source_story_id or ""),
            "source_kind": source_kind,
            "report_path": rel(report_path) if report_path else "",
        }
    )


def load_report_redirect_rows(report_paths: list[Path] | None = None) -> tuple[list[dict[str, str]], list[str], list[str]]:
    rows: list[dict[str, str]] = []
    loaded_reports: list[str] = []
    skipped_reports: list[str] = []
    paths = discover_identity_merge_reports() if report_paths is None else report_paths
    for path in paths:
        if not path.exists():
            skipped_reports.append(rel(path))
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            skipped_reports.append(rel(path))
            continue
        loaded_reports.append(rel(path))
        execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
        if execution_committed(execution):
            selected = payload.get("selected_canary") if isinstance(payload.get("selected_canary"), dict) else {}
            for old_id in selected.get("merge_dj_ids") or []:
                add_redirect_row(
                    rows,
                    old_dj_id=old_id,
                    canonical_dj_id=selected.get("canonical_dj_id"),
                    group_id=selected.get("group_id"),
                    source_story_id=payload.get("current_story_id") or path.parent.name,
                    source_kind="committed_canary_report",
                    report_path=path,
                )
        for iteration in payload.get("iterations") or []:
            if not isinstance(iteration, dict):
                continue
            iteration_execution = iteration.get("execution") if isinstance(iteration.get("execution"), dict) else {}
            if not execution_committed(iteration_execution):
                continue
            for old_id in iteration.get("merge_dj_ids") or []:
                add_redirect_row(
                    rows,
                    old_dj_id=old_id,
                    canonical_dj_id=iteration.get("canonical_dj_id"),
                    group_id=iteration.get("selected_group_id"),
                    source_story_id=iteration.get("story_label") or payload.get("current_story_id") or path.parent.name,
                    source_kind="committed_autobatch_report",
                    report_path=path,
                )
    return rows, loaded_reports, skipped_reports


def load_identity_redirects(conn: sqlite3.Connection, report_paths: list[Path] | None = None) -> dict[str, Any]:
    table_rows: list[dict[str, str]] = []
    table_present = table_exists(conn, "dj_identity_redirect")
    if table_present:
        table_rows = [
            {
                "old_dj_id": str(row[0]),
                "canonical_dj_id": str(row[1]),
                "group_id": str(row[2] or ""),
                "source_story_id": str(row[3] or ""),
                "source_kind": "db3_table",
                "report_path": "",
            }
            for row in conn.execute(
        """
        SELECT old_dj_id, canonical_dj_id, group_id, source_story_id
        FROM dj_identity_redirect
        WHERE COALESCE(old_dj_id, '') <> ''
          AND COALESCE(canonical_dj_id, '') <> ''
        ORDER BY old_dj_id
        """
            ).fetchall()
        ]
    report_rows, loaded_reports, skipped_reports = load_report_redirect_rows(report_paths)
    rows: list[dict[str, str]] = []
    redirect_map: dict[str, str] = {}
    conflicts: list[dict[str, Any]] = []
    for row in [*table_rows, *report_rows]:
        old_id = row["old_dj_id"]
        canonical_id = row["canonical_dj_id"]
        current = redirect_map.get(old_id)
        if current and current != canonical_id:
            conflicts.append({"old_dj_id": old_id, "existing_canonical_dj_id": current, "new": row})
            continue
        if not current:
            rows.append(row)
        redirect_map[old_id] = canonical_id
    invalid = [
        row
        for row in rows
        if not conn.execute("SELECT 1 FROM dj_profile WHERE dj_id=?", (row["canonical_dj_id"],)).fetchone()
    ]
    return {
        "table_present": table_present,
        "table_row_count": len(table_rows),
        "report_row_count": len(report_rows),
        "row_count": len(rows),
        "redirect_map": redirect_map,
        "loaded_report_count": len(loaded_reports),
        "loaded_reports": loaded_reports,
        "skipped_reports": skipped_reports,
        "conflict_count": len(conflicts),
        "conflict_sample": conflicts[:20],
        "invalid_canonical_count": len(invalid),
        "invalid_canonical_sample": invalid[:20],
        "sample": rows[:20],
    }


def canonicalize_dj_id(value: Any, redirect_map: dict[str, str]) -> str:
    current = str(value or "")
    seen: set[str] = set()
    for _ in range(12):
        if not current or current in seen or current not in redirect_map:
            return current
        seen.add(current)
        current = redirect_map[current]
    return current


def db3_relation_pairs(conn: sqlite3.Connection, redirect_map: dict[str, str] | None = None) -> set[tuple[str, str]]:
    redirects = redirect_map or {}
    return {
        (canonicalize_dj_id(src, redirects), canonicalize_dj_id(dst, redirects))
        for src, dst in conn.execute(
            "SELECT src_dj_id, dst_dj_id FROM dj_collaborator WHERE COALESCE(src_dj_id, '') <> '' AND COALESCE(dst_dj_id, '') <> ''"
        )
    }


def compare_top_relations(
    db2: sqlite3.Connection,
    db3: sqlite3.Connection,
    limit: int,
    redirect_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    redirects = redirect_map or {}
    sample = sample_db2_relations(db2, limit)
    projected = db3_relation_pairs(db3, redirects)
    missing = []
    redirected_count = 0
    collapsed_by_redirect = 0
    for row in sample:
        src = canonicalize_dj_id(row["src_dj_id"], redirects)
        dst = canonicalize_dj_id(row["dst_dj_id"], redirects)
        if src != row["src_dj_id"] or dst != row["dst_dj_id"]:
            redirected_count += 1
        if src == dst:
            collapsed_by_redirect += 1
            continue
        pair = (src, dst)
        reverse = (dst, src)
        if pair not in projected and reverse not in projected:
            with_canonical = dict(row)
            with_canonical["canonical_src_dj_id"] = src
            with_canonical["canonical_dst_dj_id"] = dst
            missing.append(with_canonical)
    return {
        "sample_size": len(sample),
        "missing_count": len(missing),
        "missing_sample": missing[:20],
        "redirected_count": redirected_count,
        "collapsed_by_redirect_count": collapsed_by_redirect,
    }


def db3_reference_integrity(db3: sqlite3.Connection) -> dict[str, int]:
    return {
        "dj_collaborator_src_missing_profile": missing_fk_count(db3, "dj_collaborator", "src_dj_id", "dj_profile", "dj_id"),
        "dj_collaborator_dst_missing_profile": missing_fk_count(db3, "dj_collaborator", "dst_dj_id", "dj_profile", "dj_id"),
        "dj_venue_dj_missing_profile": missing_fk_count(db3, "dj_venue", "dj_id", "dj_profile", "dj_id"),
        "dj_event_dj_missing_profile": missing_fk_count(db3, "dj_event", "dj_id", "dj_profile", "dj_id"),
        "dj_profile_missing_subject": missing_fk_count(db3, "dj_profile", "dj_id", "subject", "subject_id"),
    }


def db2_top_profile_projection(
    db2: sqlite3.Connection,
    db3: sqlite3.Connection,
    limit: int,
    redirect_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    redirects = redirect_map or {}
    rows = db2.execute(
        """
        SELECT dj_id, display_name, normalized_name, event_count, collaborator_count
        FROM dj_profile
        WHERE COALESCE(dj_id, '') <> ''
        ORDER BY collaborator_count DESC, event_count DESC, dj_id
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    db3_ids = {str(row[0]) for row in db3.execute("SELECT dj_id FROM dj_profile WHERE COALESCE(dj_id, '') <> ''")}
    sample = [
        {
            "dj_id": str(row[0]),
            "display_name": row[1] or "",
            "normalized_name": row[2] or "",
            "event_count": int(row[3] or 0),
            "collaborator_count": int(row[4] or 0),
        }
        for row in rows
    ]
    missing = []
    redirected_count = 0
    for row in sample:
        canonical_id = canonicalize_dj_id(row["dj_id"], redirects)
        if canonical_id != row["dj_id"]:
            redirected_count += 1
        if canonical_id not in db3_ids:
            with_canonical = dict(row)
            with_canonical["canonical_dj_id"] = canonical_id
            missing.append(with_canonical)
    return {
        "sample_size": len(sample),
        "missing_count": len(missing),
        "missing_sample": missing[:20],
        "redirected_count": redirected_count,
    }


def load_profile_dispositions(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    if not table_exists(conn, "dj_identity_profile_disposition"):
        return {}
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(dj_identity_profile_disposition)").fetchall()}
    optional_columns = [
        column
        for column in ["source_ref_count", "event_count", "subject_present"]
        if column in columns
    ]
    select_columns = ["dj_id", "disposition", "reason_code", "source_story_id", *optional_columns]
    return {
        str(row[0]): {
            "disposition": str(row[1] or ""),
            "reason_code": str(row[2] or ""),
            "source_story_id": str(row[3] or ""),
            "source_ref_count": str(row[4 + optional_columns.index("source_ref_count")] if "source_ref_count" in optional_columns else "0"),
            "event_count": str(row[4 + optional_columns.index("event_count")] if "event_count" in optional_columns else "0"),
            "subject_present": str(row[4 + optional_columns.index("subject_present")] if "subject_present" in optional_columns else "0"),
        }
        for row in conn.execute(
            f"""
            SELECT {', '.join(select_columns)}
            FROM dj_identity_profile_disposition
            WHERE COALESCE(dj_id, '') <> ''
            """
        ).fetchall()
    }


def accepted_empty_normalized_disposition(row: dict[str, str]) -> bool:
    return row.get("disposition") in {"symbolic_stage_name_preserve", "punctuation_stage_name_preserve"}


def accepted_same_normalized_disposition(row: dict[str, str]) -> bool:
    if row.get("disposition") not in {
        "non_person_lineup_collective_or_role_artifact",
        "non_person_compound_or_role_artifact",
    }:
        return False
    return (
        int(row.get("source_ref_count") or 0) > 0
        and int(row.get("event_count") or 0) > 0
        and int(row.get("subject_present") or 0) == 1
    )


def db3_identity_dedupe_review(db3: sqlite3.Connection, *, limit: int = 80) -> dict[str, Any]:
    rows = db3.execute(
        """
        SELECT dj_id, display_name, normalized_name, aliases_json, city_primary
        FROM dj_profile
        WHERE COALESCE(dj_id, '') <> ''
        """
    ).fetchall()
    token_groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    empty_normalized = 0
    empty_normalized_profiles: list[dict[str, str]] = []
    profile_dispositions = load_profile_dispositions(db3)
    for dj_id, display_name, normalized_name, aliases_json, city in rows:
        normalized = normalized_token(normalized_name)
        display = str(display_name or "").strip()
        city_key = normalized_token(city)
        if not normalized:
            empty_normalized += 1
            disposition = profile_dispositions.get(str(dj_id), {})
            empty_normalized_profiles.append(
                {
                    "dj_id": str(dj_id),
                    "display_name": display,
                    "normalized_name": str(normalized_name or ""),
                    "city_primary": str(city or ""),
                    "disposition": disposition.get("disposition", ""),
                    "reason_code": disposition.get("reason_code", ""),
                    "source_story_id": disposition.get("source_story_id", ""),
                }
            )
        tokens = {normalized, normalized_token(display)}
        tokens.update(normalized_token(alias) for alias in parse_aliases(aliases_json))
        for token in {token for token in tokens if len(token) >= 2}:
            token_groups[(city_key, token)].append(
                {
                    "dj_id": str(dj_id),
                    "display_name": display,
                    "normalized_name": str(normalized_name or ""),
                    "city_primary": str(city or ""),
                }
            )
    alias_collision_groups = []
    exact_normalized_groups = []
    same_normalized_dispositioned_groups = []
    for (city_key, token), group in sorted(token_groups.items()):
        ids = sorted({row["dj_id"] for row in group})
        if len(ids) <= 1:
            continue
        normalized_values = sorted({normalized_token(row["normalized_name"]) for row in group if row["normalized_name"]})
        names = sorted({row["display_name"] for row in group if row["display_name"]})
        payload = {
            "city_key": city_key,
            "identity_token": token,
            "dj_ids": ids,
            "display_names": names[:12],
            "normalized_names": normalized_values[:12],
            "row_count": len(group),
        }
        if len(normalized_values) == 1 and normalized_values[0] == token:
            dispositions = [profile_dispositions.get(dj_id, {}) for dj_id in ids]
            if dispositions and all(accepted_same_normalized_disposition(row) for row in dispositions):
                payload["dispositions"] = [
                    {
                        "dj_id": dj_id,
                        "disposition": profile_dispositions.get(dj_id, {}).get("disposition", ""),
                        "reason_code": profile_dispositions.get(dj_id, {}).get("reason_code", ""),
                        "source_story_id": profile_dispositions.get(dj_id, {}).get("source_story_id", ""),
                    }
                    for dj_id in ids
                ]
                same_normalized_dispositioned_groups.append(payload)
            else:
                exact_normalized_groups.append(payload)
        else:
            alias_collision_groups.append(payload)
    unresolved_empty = [row for row in empty_normalized_profiles if not accepted_empty_normalized_disposition(row)]
    return {
        "profile_rows": len(rows),
        "empty_normalized_profile_count": empty_normalized,
        "empty_normalized_profile_dispositioned_count": empty_normalized - len(unresolved_empty),
        "empty_normalized_profile_unresolved_count": len(unresolved_empty),
        "same_normalized_multi_id_group_count": len(exact_normalized_groups),
        "same_normalized_multi_id_dispositioned_group_count": len(same_normalized_dispositioned_groups),
        "alias_token_multi_id_group_count": len(alias_collision_groups),
        "same_normalized_multi_id_groups": exact_normalized_groups,
        "same_normalized_multi_id_dispositioned_groups": same_normalized_dispositioned_groups,
        "alias_token_multi_id_groups": alias_collision_groups,
        "empty_normalized_profile_sample": empty_normalized_profiles[:limit],
        "empty_normalized_profile_unresolved_sample": unresolved_empty[:limit],
        "same_normalized_multi_id_sample": exact_normalized_groups[:limit],
        "same_normalized_multi_id_dispositioned_sample": same_normalized_dispositioned_groups[:limit],
        "alias_token_multi_id_sample": alias_collision_groups[:limit],
        "profile_disposition_count": len(profile_dispositions),
    }


def coverage(conn: sqlite3.Connection, table: str, fields: list[str]) -> dict[str, Any]:
    total = table_count(conn, table)
    return {
        "row_count": total,
        "fields": {
            field: {
                "non_empty": non_empty_count(conn, table, field),
                "non_empty_rate": round(non_empty_count(conn, table, field) / max(total, 1), 6),
            }
            for field in fields
        },
    }


def read_weekly_current_relation_risk(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": rel(path), "exists": False, "item_count": 0, "relation_like_field_count": 0}
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("items") if isinstance(payload, dict) else payload if isinstance(payload, list) else []
    if not isinstance(items, list):
        items = []
    relation_keys = {
        "collaborators",
        "relations",
        "sameEventCount",
        "frequentVenues",
        "residentDJs",
        "history",
        "sourceRefs",
    }
    relation_like = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        if any(item.get(key) not in (None, "", [], {}) for key in relation_keys):
            relation_like += 1
    return {
        "path": rel(path),
        "exists": True,
        "item_count": len(items),
        "relation_like_field_count": relation_like,
        "overwrite_rule": "weekly current relation-like empties must not overwrite DB2/DB3 relation tables",
    }


def build_report(
    db2_path: Path,
    db3_path: Path,
    weekly_current_path: Path,
    out_dir: Path,
    *,
    sample_limit: int,
    identity_merge_reports: list[Path] | None = None,
    auto_discover_identity_merge_reports: bool = False,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    redirect_report_paths = None if auto_discover_identity_merge_reports else (identity_merge_reports or [])
    with connect_ro(db2_path) as db2, connect_ro(db3_path) as db3:
        db2_counts = {
            "dj_relation_rollup": table_count(db2, "dj_relation_rollup"),
            "dj_venue_rollup": table_count(db2, "dj_venue_rollup"),
            "dj_event": table_count(db2, "dj_event"),
            "evidence_ref": table_count(db2, "evidence_ref"),
        }
        db3_counts = {
            "dj_collaborator": table_count(db3, "dj_collaborator"),
            "dj_venue": table_count(db3, "dj_venue"),
            "dj_event": table_count(db3, "dj_event"),
            "source_ref": table_count(db3, "source_ref"),
            "dj_profile": table_count(db3, "dj_profile"),
        }
        db2_identity_invalid = invalid_identity_count(db2, "dj_relation_rollup", "src_dj_id", "dst_dj_id")
        db3_identity_invalid = invalid_identity_count(db3, "dj_collaborator", "src_dj_id", "dst_dj_id")
        if db2_identity_invalid:
            findings.append({"severity": "high", "check": "db2_relation_identity_invalid", "count": db2_identity_invalid})
        if db3_identity_invalid:
            findings.append({"severity": "high", "check": "db3_relation_identity_invalid", "count": db3_identity_invalid})

        identity_redirect = load_identity_redirects(db3, redirect_report_paths)
        redirect_map = identity_redirect["redirect_map"]
        if identity_redirect["conflict_count"]:
            findings.append(
                {
                    "severity": "high",
                    "check": "db3_identity_redirect_conflict",
                    "count": identity_redirect["conflict_count"],
                    "sample": identity_redirect["conflict_sample"],
                }
            )
        if identity_redirect["invalid_canonical_count"]:
            findings.append(
                {
                    "severity": "high",
                    "check": "db3_identity_redirect_invalid_canonical",
                    "count": identity_redirect["invalid_canonical_count"],
                    "sample": identity_redirect["invalid_canonical_sample"],
                }
            )

        top_relation_projection = compare_top_relations(db2, db3, sample_limit, redirect_map)
        if top_relation_projection["missing_count"]:
            findings.append(
                {
                    "severity": "high",
                    "check": "top_db2_relations_missing_from_db3",
                    "count": top_relation_projection["missing_count"],
                    "sample": top_relation_projection["missing_sample"],
                }
            )

        top_profile_projection = db2_top_profile_projection(db2, db3, sample_limit, redirect_map)
        if top_profile_projection["missing_count"]:
            findings.append(
                {
                    "severity": "high",
                    "check": "top_db2_profiles_missing_from_db3",
                    "count": top_profile_projection["missing_count"],
                    "sample": top_profile_projection["missing_sample"],
                }
            )

        reference_integrity = db3_reference_integrity(db3)
        for check, count in reference_integrity.items():
            if count:
                findings.append({"severity": "high", "check": check, "count": count})

        identity_dedupe_review = db3_identity_dedupe_review(db3)
        if identity_dedupe_review["empty_normalized_profile_unresolved_count"]:
            findings.append(
                {
                    "severity": "high",
                    "check": "db3_profile_empty_normalized_name",
                    "count": identity_dedupe_review["empty_normalized_profile_unresolved_count"],
                    "total_count": identity_dedupe_review["empty_normalized_profile_count"],
                    "dispositioned_count": identity_dedupe_review["empty_normalized_profile_dispositioned_count"],
                    "sample": identity_dedupe_review["empty_normalized_profile_unresolved_sample"][:20],
                }
            )
        if identity_dedupe_review["same_normalized_multi_id_group_count"]:
            findings.append(
                {
                    "severity": "high",
                    "check": "db3_same_normalized_name_multi_id",
                    "count": identity_dedupe_review["same_normalized_multi_id_group_count"],
                    "sample": identity_dedupe_review["same_normalized_multi_id_sample"][:20],
                }
            )

        db3_source_ref_missing = scalar(
            db3,
            """
            SELECT COUNT(*)
            FROM dj_event
            WHERE COALESCE(source_ref_id, '') <> ''
              AND source_ref_id NOT IN (SELECT source_ref_id FROM source_ref)
            """,
        )
        if db3_source_ref_missing:
            findings.append({"severity": "high", "check": "db3_dj_event_source_ref_lookup_missing", "count": db3_source_ref_missing})

        db3_coverages = {
            "dj_collaborator": coverage(db3, "dj_collaborator", ["src_dj_id", "dst_dj_id", "same_event_count", "relation_score"]),
            "dj_venue": coverage(db3, "dj_venue", ["dj_id", "venue_id", "venue_name", "city", "event_count"]),
            "dj_event": coverage(db3, "dj_event", ["dj_id", "event_id", "venue_id", "venue_name", "city", "source_ref_id"]),
            "source_ref": coverage(db3, "source_ref", ["source_ref_id", "source_hash", "source_account", "source_title", "source_kind"]),
        }
        for table, table_info in db3_coverages.items():
            for field, field_info in table_info["fields"].items():
                if table_info["row_count"] and field_info["non_empty"] == 0:
                    findings.append({"severity": "high", "check": f"{table}_{field}_all_empty", "table": table, "field": field})

    weekly_current = read_weekly_current_relation_risk(weekly_current_path)
    decision = "atlas_relation_field_integrity_passed" if not any(f["severity"] == "high" for f in findings) else "atlas_relation_field_integrity_findings"
    report = {
        "schema_version": "atlas_relation_field_integrity.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "decision": decision,
        "findings": findings,
        "db2_path": rel(db2_path),
        "db3_path": rel(db3_path),
        "db2_counts": db2_counts,
        "db3_counts": db3_counts,
        "db3_coverage": db3_coverages,
        "top_relation_projection": top_relation_projection,
        "top_profile_projection": top_profile_projection,
        "identity_redirect": {key: value for key, value in identity_redirect.items() if key != "redirect_map"},
        "db2_relation_identity_invalid_count": db2_identity_invalid,
        "db3_relation_identity_invalid_count": db3_identity_invalid,
        "db3_reference_integrity": reference_integrity,
        "db3_identity_dedupe_review": identity_dedupe_review,
        "db3_dj_event_source_ref_lookup_missing_count": db3_source_ref_missing,
        "weekly_current_relation_overwrite_risk": weekly_current,
        "rules": [
            "DB2 relation/read-model rows are the authority for DJ-DJ and DJ-venue rollups.",
            "DB3 is a mobile projection; it may be smaller than DB2, but high-confidence DB2 relations must not disappear from DB3.",
            "DB3 relation/event/venue rows must point to existing DJ profiles, and DJ profiles must have matching subject rows.",
            "DB2 to DB3 comparisons canonicalize through DB3 dj_identity_redirect or committed DB3 identity merge reports when DB3 has already merged an old DJ ID into a canonical DJ profile.",
            "Duplicate DJ identity tokens are review material unless they share the same normalized name, which is a high-risk projection split.",
            "Weekly current empty relation-like fields must never overwrite DB2/DB3 history, collaborators, venues, or source refs.",
            "Promotion and repair lanes must use non-empty coalescing and explicit review gates before replacing relation fields.",
        ],
        "safety": {
            "report_only": True,
            "database_mutations": False,
            "secret_files_read": False,
            "model_calls_performed": False,
            "deployment_executed": False,
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "atlas_relation_field_integrity.json", report)
    write_markdown(out_dir / "atlas_relation_field_integrity.md", report)
    return report


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Atlas Relation Field Integrity",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Findings: `{len(report['findings'])}`",
        f"- DB2: `{report['db2_path']}`",
        f"- DB3: `{report['db3_path']}`",
        "",
        "## Counts",
        "",
        "### DB2",
    ]
    for key, value in report["db2_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "### DB3"])
    for key, value in report["db3_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## DB3 Field Coverage"])
    for table, table_info in report["db3_coverage"].items():
        lines.append(f"- `{table}` rows `{table_info['row_count']}`")
        for field, info in table_info["fields"].items():
            lines.append(f"  - `{field}` non-empty `{info['non_empty']}` rate `{info['non_empty_rate']}`")
    projection = report["top_relation_projection"]
    lines.extend(
        [
            "",
            "## DB3 Identity Redirect",
            f"- Table present: `{report.get('identity_redirect', {}).get('table_present')}`",
            f"- Redirect rows: `{report.get('identity_redirect', {}).get('row_count')}`",
            f"- Table redirect rows: `{report.get('identity_redirect', {}).get('table_row_count')}`",
            f"- Committed report redirect rows: `{report.get('identity_redirect', {}).get('report_row_count')}`",
            f"- Loaded merge reports: `{report.get('identity_redirect', {}).get('loaded_report_count')}`",
            f"- Redirect conflicts: `{report.get('identity_redirect', {}).get('conflict_count')}`",
            f"- Invalid canonical redirects: `{report.get('identity_redirect', {}).get('invalid_canonical_count')}`",
            "",
            "## Top DB2 Relation Projection",
            f"- Sample size: `{projection['sample_size']}`",
            f"- Missing from DB3: `{projection['missing_count']}`",
            f"- Redirected through canonical IDs: `{projection.get('redirected_count', 0)}`",
            f"- Collapsed by identity redirect: `{projection.get('collapsed_by_redirect_count', 0)}`",
            "",
            "## Top DB2 Profile Projection",
            f"- Sample size: `{report['top_profile_projection']['sample_size']}`",
            f"- Missing from DB3: `{report['top_profile_projection']['missing_count']}`",
            f"- Redirected through canonical IDs: `{report['top_profile_projection'].get('redirected_count', 0)}`",
            "",
            "## DB3 Identity Reference Integrity",
        ]
    )
    for key, value in report["db3_reference_integrity"].items():
        lines.append(f"- `{key}`: `{value}`")
    identity = report["db3_identity_dedupe_review"]
    lines.extend(
        [
            "",
            "## DB3 Identity Dedupe Review",
            f"- Profile rows: `{identity['profile_rows']}`",
            f"- Empty normalized profiles: `{identity['empty_normalized_profile_count']}`",
            f"- Empty normalized profiles dispositioned: `{identity.get('empty_normalized_profile_dispositioned_count', 0)}`",
            f"- Empty normalized profiles unresolved: `{identity.get('empty_normalized_profile_unresolved_count', identity['empty_normalized_profile_count'])}`",
            f"- Same normalized-name multi-id groups: `{identity['same_normalized_multi_id_group_count']}`",
            f"- Same normalized-name non-person dispositioned groups: `{identity.get('same_normalized_multi_id_dispositioned_group_count', 0)}`",
            f"- Alias-token multi-id review groups: `{identity['alias_token_multi_id_group_count']}`",
            "",
            "## Source Ref Integrity",
            f"- DB3 `dj_event.source_ref_id` missing lookup count: `{report['db3_dj_event_source_ref_lookup_missing_count']}`",
            "",
            "## Empty Overwrite Boundary",
            f"- Weekly current items: `{report['weekly_current_relation_overwrite_risk'].get('item_count', 0)}`",
            f"- Weekly current relation-like fields: `{report['weekly_current_relation_overwrite_risk'].get('relation_like_field_count', 0)}`",
            f"- Rule: {report['weekly_current_relation_overwrite_risk'].get('overwrite_rule', '')}",
            "",
            "## Rules",
        ]
    )
    for rule in report["rules"]:
        lines.append(f"- {rule}")
    if report["findings"]:
        lines.extend(["", "## Findings"])
        for finding in report["findings"]:
            lines.append(f"- `{finding['severity']}` `{finding['check']}` count `{finding.get('count', '')}`")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit DB2/DB3 Atlas relation field integrity")
    parser.add_argument("--db2", type=Path, default=DEFAULT_DB2)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--weekly-current", type=Path, default=DEFAULT_WEEKLY_CURRENT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--sample-limit", type=int, default=500)
    parser.add_argument("--identity-merge-report", type=Path, action="append", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        args.db2,
        args.db3,
        args.weekly_current,
        args.out_dir,
        sample_limit=args.sample_limit,
        identity_merge_reports=args.identity_merge_report,
        auto_discover_identity_merge_reports=args.identity_merge_report is None,
    )
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "findings": len(report["findings"]),
                "top_missing": report["top_relation_projection"]["missing_count"],
                "top_profile_missing": report["top_profile_projection"]["missing_count"],
                "identity_alias_review_groups": report["db3_identity_dedupe_review"]["alias_token_multi_id_group_count"],
                "db3_source_ref_missing": report["db3_dj_event_source_ref_lookup_missing_count"],
                "json": str(args.out_dir / "atlas_relation_field_integrity.json"),
                "markdown": str(args.out_dir / "atlas_relation_field_integrity.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["decision"] == "atlas_relation_field_integrity_passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
