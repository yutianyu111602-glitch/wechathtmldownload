#!/usr/bin/env python3
"""Build a no-write source-evidence enrichment packet for relation identity rows.

The S138 workbench intentionally leaves source/disposition fields blank. This
script reconnects those workbench rows to the original identity queues, then
queries DB3 read-only for profile/event/source_ref/venue/collaborator evidence.
It does not approve merges or mutate any database.
"""
from __future__ import annotations

import argparse
import html
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_WORKBENCH = (
    REPORTS_ROOT
    / "atlas_relation_identity_source_ref_disposition_workbench_s138_20260602"
    / "atlas_relation_identity_source_ref_disposition_workbench.json"
)
DEFAULT_HIGH_RISK_NEXT_ACTION = (
    REPORTS_ROOT
    / "atlas_dj_identity_next_action_packet_s86_20260531"
    / "atlas_dj_identity_next_action_packet.json"
)
DEFAULT_NON_HIGH_QUEUE = (
    REPORTS_ROOT
    / "atlas_dj_identity_non_high_review_batch_queue_s87_20260531"
    / "atlas_dj_identity_non_high_review_batch_queue.json"
)
DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_source_evidence_enrichment_s139_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_SOURCE_EVIDENCE_ENRICHMENT_S139_20260602.md"
CURRENT_STORY_ID = "S139"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(read_text(path))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def compact(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def connect_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def source_row_index(high_risk_next_action: dict[str, Any], non_high_queue: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in as_list(high_risk_next_action.get("next_action_rows")):
        if isinstance(row, dict):
            task_id = str(row.get("identity_next_action_task_id") or "")
            if task_id:
                index[task_id] = row
    for row in as_list(non_high_queue.get("non_high_review_queue_rows")):
        if isinstance(row, dict):
            task_id = str(row.get("non_high_review_task_id") or "")
            if task_id:
                index[task_id] = row
    return index


def placeholders(values: list[str]) -> str:
    return ",".join("?" for _ in values)


def query_profiles(conn: sqlite3.Connection, dj_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not dj_ids:
        return {}
    rows = conn.execute(
        f"""
        SELECT dj_id, display_name, normalized_name, aliases_json, city_primary,
               event_count, venue_count, collaborator_count, first_seen_at, last_seen_at,
               bio, bio_source, avatar_url
        FROM dj_profile
        WHERE dj_id IN ({placeholders(dj_ids)})
        """,
        tuple(dj_ids),
    ).fetchall()
    return {
        str(row["dj_id"]): {
            "dj_id": str(row["dj_id"]),
            "display_name": str(row["display_name"] or ""),
            "normalized_name": str(row["normalized_name"] or ""),
            "aliases_json": str(row["aliases_json"] or ""),
            "city_primary": str(row["city_primary"] or ""),
            "event_count": int_value(row["event_count"]),
            "venue_count": int_value(row["venue_count"]),
            "collaborator_count": int_value(row["collaborator_count"]),
            "first_seen_at": str(row["first_seen_at"] or ""),
            "last_seen_at": str(row["last_seen_at"] or ""),
            "has_bio": bool(str(row["bio"] or "").strip()),
            "bio_source": str(row["bio_source"] or ""),
            "has_avatar": bool(str(row["avatar_url"] or "").strip()),
        }
        for row in rows
    }


def query_events_for_dj(conn: sqlite3.Connection, dj_id: str, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT de.dj_id, de.event_id, de.starts_at, de.event_title, de.venue_id,
               de.venue_name, de.city, de.source_ref_id, de.confidence,
               sr.source_hash, sr.source_account, sr.source_title, sr.post_date, sr.source_kind
        FROM dj_event de
        LEFT JOIN source_ref sr ON sr.source_ref_id = de.source_ref_id
        WHERE de.dj_id = ?
        ORDER BY CASE WHEN COALESCE(de.source_ref_id, '') <> '' THEN 0 ELSE 1 END,
                 de.starts_at DESC,
                 de.event_id
        LIMIT ?
        """,
        (dj_id, limit),
    ).fetchall()
    return [
        {
            "dj_id": str(row["dj_id"] or ""),
            "event_id": str(row["event_id"] or ""),
            "starts_at": str(row["starts_at"] or ""),
            "event_title": compact(row["event_title"], 180),
            "venue_id": str(row["venue_id"] or ""),
            "venue_name": compact(row["venue_name"], 120),
            "city": str(row["city"] or ""),
            "source_ref_id": str(row["source_ref_id"] or ""),
            "source_hash": str(row["source_hash"] or ""),
            "source_account": compact(row["source_account"], 120),
            "source_title": compact(row["source_title"], 180),
            "post_date": str(row["post_date"] or ""),
            "source_kind": str(row["source_kind"] or ""),
            "confidence": float(row["confidence"] or 0),
        }
        for row in rows
    ]


def query_venues_for_dj(conn: sqlite3.Connection, dj_id: str, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT dj_id, venue_id, venue_name, city, event_count, first_seen_at, last_seen_at
        FROM dj_venue
        WHERE dj_id = ?
        ORDER BY event_count DESC, last_seen_at DESC, venue_id
        LIMIT ?
        """,
        (dj_id, limit),
    ).fetchall()
    return [
        {
            "dj_id": str(row["dj_id"] or ""),
            "venue_id": str(row["venue_id"] or ""),
            "venue_name": compact(row["venue_name"], 120),
            "city": str(row["city"] or ""),
            "event_count": int_value(row["event_count"]),
            "first_seen_at": str(row["first_seen_at"] or ""),
            "last_seen_at": str(row["last_seen_at"] or ""),
        }
        for row in rows
    ]


def query_collaborators_for_dj(conn: sqlite3.Connection, dj_id: str, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT dc.src_dj_id, dc.dst_dj_id, dc.same_event_count, dc.relation_label_zh, dc.relation_score,
               sp.display_name AS src_display_name, dp.display_name AS dst_display_name
        FROM dj_collaborator dc
        LEFT JOIN dj_profile sp ON sp.dj_id = dc.src_dj_id
        LEFT JOIN dj_profile dp ON dp.dj_id = dc.dst_dj_id
        WHERE dc.src_dj_id = ? OR dc.dst_dj_id = ?
        ORDER BY dc.same_event_count DESC, dc.relation_score DESC, dc.src_dj_id, dc.dst_dj_id
        LIMIT ?
        """,
        (dj_id, dj_id, limit),
    ).fetchall()
    return [
        {
            "src_dj_id": str(row["src_dj_id"] or ""),
            "dst_dj_id": str(row["dst_dj_id"] or ""),
            "src_display_name": compact(row["src_display_name"], 100),
            "dst_display_name": compact(row["dst_display_name"], 100),
            "same_event_count": int_value(row["same_event_count"]),
            "relation_label_zh": str(row["relation_label_zh"] or ""),
            "relation_score": float(row["relation_score"] or 0),
        }
        for row in rows
    ]


def unique_source_candidates(events_by_dj: dict[str, list[dict[str, Any]]], limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for dj_id, events in events_by_dj.items():
        for event in events:
            source_ref_id = str(event.get("source_ref_id") or "")
            if not source_ref_id or source_ref_id in seen:
                continue
            seen.add(source_ref_id)
            candidates.append(
                {
                    "source_ref_id": source_ref_id,
                    "source_hash": event.get("source_hash", ""),
                    "source_account": event.get("source_account", ""),
                    "source_title": event.get("source_title", ""),
                    "post_date": event.get("post_date", ""),
                    "source_kind": event.get("source_kind", ""),
                    "evidence_event_id": event.get("event_id", ""),
                    "evidence_event_title": event.get("event_title", ""),
                    "evidence_starts_at": event.get("starts_at", ""),
                    "evidence_venue_name": event.get("venue_name", ""),
                    "evidence_city": event.get("city", ""),
                    "evidence_dj_id": dj_id,
                }
            )
            if len(candidates) >= limit:
                return candidates
    return candidates


def build_draft_suggestions(row: dict[str, Any], candidates: list[dict[str, Any]], missing_source_dj_ids: list[str]) -> dict[str, str]:
    first = candidates[0] if candidates else {}
    missing_note = ""
    if missing_source_dj_ids:
        missing_note = " Missing source_ref evidence for: " + ", ".join(missing_source_dj_ids[:8]) + "."
    return {
        "source_ref_id_or_original_url": str(first.get("source_ref_id") or ""),
        "source_account_or_platform": str(first.get("source_account") or ""),
        "published_at_or_event_date": str(first.get("post_date") or first.get("evidence_starts_at") or ""),
        "evidence_title_or_quote": compact(
            first.get("source_title") or first.get("evidence_event_title") or "",
            220,
        ),
        "identity_match_notes": (
            "DB3 read-only evidence collected for manual identity review. "
            "Same normalized name is not treated as sufficient merge proof."
            + missing_note
        ).strip(),
        "field_preservation_notes": (
            "Before any future write gate, preserve non-empty dj_event, dj_venue, "
            "dj_collaborator, source_ref, bio, avatar, aliases, and display names."
        ),
        "disposition": "needs_more_evidence",
        "reviewer_notes": "Report-only suggestion; no approval or write-gate authorization.",
    }


def enrich_row(
    row: dict[str, Any],
    *,
    source_index: dict[str, dict[str, Any]],
    conn: sqlite3.Connection,
    per_dj_event_limit: int,
    per_dj_venue_limit: int,
    per_dj_collab_limit: int,
    source_candidate_limit: int,
) -> dict[str, Any]:
    source_task_id = str(row.get("source_starter_task_id") or "")
    source = source_index.get(source_task_id, {})
    all_dj_ids = [str(item) for item in as_list(source.get("all_dj_ids")) if item]
    if not all_dj_ids:
        fallback_ids = [row.get("canonical_dj_id"), *as_list(source.get("merge_dj_ids"))]
        all_dj_ids = [str(item) for item in fallback_ids if item]
    profiles = query_profiles(conn, all_dj_ids)
    events_by_dj = {dj_id: query_events_for_dj(conn, dj_id, per_dj_event_limit) for dj_id in all_dj_ids}
    venues_by_dj = {dj_id: query_venues_for_dj(conn, dj_id, per_dj_venue_limit) for dj_id in all_dj_ids}
    collaborators_by_dj = {
        dj_id: query_collaborators_for_dj(conn, dj_id, per_dj_collab_limit) for dj_id in all_dj_ids
    }
    source_candidates = unique_source_candidates(events_by_dj, source_candidate_limit)
    ids_with_source = sorted(
        dj_id
        for dj_id, events in events_by_dj.items()
        if any(str(event.get("source_ref_id") or "").strip() for event in events)
    )
    missing_source_dj_ids = [dj_id for dj_id in all_dj_ids if dj_id not in set(ids_with_source)]
    field_presence = {
        "profile_rows": len(profiles),
        "profile_rows_with_bio": sum(1 for profile in profiles.values() if profile["has_bio"]),
        "profile_rows_with_avatar": sum(1 for profile in profiles.values() if profile["has_avatar"]),
        "sampled_event_rows": sum(len(events) for events in events_by_dj.values()),
        "sampled_venue_rows": sum(len(venues) for venues in venues_by_dj.values()),
        "sampled_collaborator_edges": sum(len(collabs) for collabs in collaborators_by_dj.values()),
        "source_ref_candidates": len(source_candidates),
        "all_dj_ids": len(all_dj_ids),
        "dj_ids_with_source_ref": len(ids_with_source),
    }
    evidence_state = (
        "manual_disposition_ready_candidate"
        if all_dj_ids and not missing_source_dj_ids and source_candidates
        else "needs_more_source_ref_collection"
    )
    return {
        "workbench_row_id": row.get("workbench_row_id", ""),
        "source_starter_task_id": source_task_id,
        "review_order": row.get("review_order"),
        "lane": row.get("lane"),
        "risk_level": row.get("risk_level"),
        "group_id": row.get("group_id"),
        "city_key": row.get("city_key"),
        "display_names": as_list(row.get("display_names")),
        "canonical_dj_id": row.get("canonical_dj_id"),
        "merge_dj_ids": [str(item) for item in as_list(source.get("merge_dj_ids")) if item],
        "all_dj_ids": all_dj_ids,
        "source_identity_row_found": bool(source),
        "source_identity_fields": {
            "identity_token": source.get("identity_token", row.get("group_id")),
            "normalized_names": as_list(source.get("normalized_names")),
            "reason_codes": as_list(source.get("reason_codes")) or as_list(row.get("reason_codes")),
            "required_evidence_checks": as_list(source.get("required_evidence_checks"))
            or as_list(row.get("required_evidence_checks")),
        },
        "profile_evidence": [profiles[dj_id] for dj_id in all_dj_ids if dj_id in profiles],
        "event_evidence_by_dj": events_by_dj,
        "venue_evidence_by_dj": venues_by_dj,
        "collaborator_evidence_by_dj": collaborators_by_dj,
        "source_ref_candidates": source_candidates,
        "field_presence": field_presence,
        "ids_with_source_ref": ids_with_source,
        "missing_source_ref_dj_ids": missing_source_dj_ids,
        "evidence_state": evidence_state,
        "suggested_draft": build_draft_suggestions(row, source_candidates, missing_source_dj_ids),
        "ready_for_validation": False,
        "approved_for_write_gate": False,
        "write_gate_candidate": False,
        "safe_automerge": False,
        "database_write_allowed": False,
    }


def build_report(
    *,
    workbench_path: Path,
    high_risk_next_action_path: Path,
    non_high_queue_path: Path,
    db3_path: Path,
    per_dj_event_limit: int,
    per_dj_venue_limit: int,
    per_dj_collab_limit: int,
    source_candidate_limit: int,
) -> dict[str, Any]:
    workbench = read_json(workbench_path)
    high_risk = read_json(high_risk_next_action_path)
    non_high = read_json(non_high_queue_path)
    index = source_row_index(high_risk, non_high)
    rows = [row for row in as_list(workbench.get("review_rows")) if isinstance(row, dict)]
    with connect_ro(db3_path) as conn:
        enriched_rows = [
            enrich_row(
                row,
                source_index=index,
                conn=conn,
                per_dj_event_limit=per_dj_event_limit,
                per_dj_venue_limit=per_dj_venue_limit,
                per_dj_collab_limit=per_dj_collab_limit,
                source_candidate_limit=source_candidate_limit,
            )
            for row in rows
        ]
    lane_counts = Counter(str(row.get("lane") or "") for row in enriched_rows)
    evidence_state_counts = Counter(str(row.get("evidence_state") or "") for row in enriched_rows)
    missing_index_count = sum(1 for row in enriched_rows if not row["source_identity_row_found"])
    rows_with_source_refs = sum(1 for row in enriched_rows if row["field_presence"]["source_ref_candidates"] > 0)
    all_ids_source_ref_count = sum(
        1
        for row in enriched_rows
        if row["field_presence"]["all_dj_ids"] > 0
        and row["field_presence"]["all_dj_ids"] == row["field_presence"]["dj_ids_with_source_ref"]
    )
    decision = (
        "atlas_relation_identity_source_evidence_enrichment_ready_for_manual_disposition_report_only"
        if rows_with_source_refs and not missing_index_count
        else "atlas_relation_identity_source_evidence_enrichment_pending_report_only"
    )
    return {
        "schema_version": "atlas_relation_identity_source_evidence_enrichment.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "current_story_id": CURRENT_STORY_ID,
        "decision": decision,
        "source_inputs": {
            "workbench": rel_path(workbench_path),
            "high_risk_next_action": rel_path(high_risk_next_action_path),
            "non_high_queue": rel_path(non_high_queue_path),
            "db3": rel_path(db3_path),
        },
        "input_workbench_decision": workbench.get("decision"),
        "input_row_count": len(rows),
        "enriched_row_count": len(enriched_rows),
        "lane_counts": dict(sorted(lane_counts.items())),
        "evidence_state_counts": dict(sorted(evidence_state_counts.items())),
        "source_identity_missing_index_count": missing_index_count,
        "rows_with_source_ref_candidates": rows_with_source_refs,
        "rows_with_all_ids_source_ref_candidates": all_ids_source_ref_count,
        "ready_for_validation_count": 0,
        "approved_for_write_gate_count": 0,
        "write_gate_candidate_count": 0,
        "safe_automerge_allowed": False,
        "database_write_allowed": False,
        "query_limits": {
            "per_dj_event_limit": per_dj_event_limit,
            "per_dj_venue_limit": per_dj_venue_limit,
            "per_dj_collab_limit": per_dj_collab_limit,
            "source_candidate_limit": source_candidate_limit,
        },
        "enriched_rows": enriched_rows,
        "next_action_tasks": [
            {
                "task_id": "s139:review_enriched_source_ref_candidates",
                "requirement_id": "relation_identity_write_gate",
                "status": "blocked_pending_manual_identity_disposition",
                "hard_blocking": True,
                "detail": {
                    "row_count": len(enriched_rows),
                    "rows_with_source_ref_candidates": rows_with_source_refs,
                    "rows_with_all_ids_source_ref_candidates": all_ids_source_ref_count,
                },
            },
            {
                "task_id": "s139:do_not_write_until_disposition_validation_passes",
                "requirement_id": "relation_identity_write_gate",
                "status": "blocked_pending_approved_disposition_packet",
                "hard_blocking": True,
                "detail": {
                    "approved_for_write_gate_count": 0,
                    "write_gate_candidate_count": 0,
                },
            },
        ],
        "rules": [
            "This packet enriches review rows with existing DB3 source evidence only.",
            "Suggested drafts are not approvals and must not be copied into a write gate without review validation.",
            "Same normalized name remains insufficient merge evidence.",
            "Rows with missing source_ref candidates require more source collection before disposition.",
        ],
        "safety": {
            "report_only": True,
            "database_mutations": False,
            "identity_merge_executed": False,
            "write_gate_authorized": False,
            "graph_vector_public_pointer_write": False,
            "coordinate_write": False,
            "provider_or_geocode_call": False,
            "provider_or_llm_call": False,
            "deploy_upload_review": False,
            "secret_read": False,
            "release_rebuild": False,
            "service_restart": False,
            "broad_disk_scan": False,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Atlas Relation Identity Source Evidence Enrichment",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Current story: `{report['current_story_id']}`",
        f"- Workbench: `{report['source_inputs']['workbench']}`",
        f"- DB3: `{report['source_inputs']['db3']}`",
        f"- Enriched rows: `{report['enriched_row_count']}`",
        f"- Rows with source-ref candidates: `{report['rows_with_source_ref_candidates']}`",
        f"- Rows with all IDs carrying source-ref candidates: `{report['rows_with_all_ids_source_ref_candidates']}`",
        f"- Missing source identity index rows: `{report['source_identity_missing_index_count']}`",
        f"- Ready for validation: `{report['ready_for_validation_count']}`",
        f"- Approved write-gate rows: `{report['approved_for_write_gate_count']}`",
        "",
        "## Evidence State Counts",
        "",
    ]
    for key, value in report["evidence_state_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Review Rows",
            "",
            "| Order | Lane | Group | Names | Source Candidates | All IDs Covered | State |",
            "| --- | --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    for row in report["enriched_rows"]:
        names = ", ".join(str(name) for name in row["display_names"][:5]).replace("|", "\\|")
        all_ids = row["field_presence"]["all_dj_ids"]
        with_refs = row["field_presence"]["dj_ids_with_source_ref"]
        lines.append(
            f"| `{row['review_order']}` | `{row['lane']}` | `{row['group_id']}` | {names} | "
            f"`{row['field_presence']['source_ref_candidates']}` | `{with_refs}/{all_ids}` | `{row['evidence_state']}` |"
        )
    lines.extend(["", "## Next Safe Actions", ""])
    for task in report["next_action_tasks"]:
        lines.append(f"- `{task['task_id']}`: `{task['status']}`; hard_blocking=`{task['hard_blocking']}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This packet is report-only. It read DB3 in read-only mode and did not merge identities, mutate DB/graph/vector state, authorize a write gate, call providers or LLMs, deploy, upload, read secrets, rebuild releases, restart services, or scan broad disks.",
            "",
        ]
    )
    return "\n".join(lines)


def render_html(report: dict[str, Any]) -> str:
    rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(row['review_order']))}</td>"
        f"<td>{html.escape(str(row['lane']))}</td>"
        f"<td>{html.escape(str(row['group_id']))}</td>"
        f"<td>{html.escape(', '.join(str(name) for name in row['display_names'][:5]))}</td>"
        f"<td>{row['field_presence']['source_ref_candidates']}</td>"
        f"<td>{row['field_presence']['dj_ids_with_source_ref']}/{row['field_presence']['all_dj_ids']}</td>"
        f"<td>{html.escape(str(row['evidence_state']))}</td>"
        "</tr>"
        for row in report["enriched_rows"]
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Atlas Relation Identity S139 Evidence</title>
  <style>
    body {{ margin: 0; font-family: Segoe UI, Microsoft YaHei, Arial, sans-serif; background: #f6f8fb; color: #1f2933; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px 22px 48px; }}
    h1 {{ margin: 0 0 8px; font-size: 26px; }}
    .meta {{ color: #667085; margin-bottom: 18px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 18px 0; }}
    .card {{ background: #fff; border: 1px solid #d9dee7; border-radius: 8px; padding: 14px; }}
    .num {{ font-size: 24px; font-weight: 700; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d9dee7; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid #d9dee7; text-align: left; font-size: 13px; vertical-align: top; }}
    th {{ background: #eef2f6; }}
    code {{ background: #eef2f6; border: 1px solid #d9dee7; border-radius: 4px; padding: 1px 5px; }}
  </style>
</head>
<body>
  <main>
    <h1>Atlas Relation Identity S139 Evidence</h1>
    <div class="meta">Decision: <code>{html.escape(report['decision'])}</code></div>
    <section class="grid">
      <div class="card"><div class="num">{report['enriched_row_count']}</div><div>enriched rows</div></div>
      <div class="card"><div class="num">{report['rows_with_source_ref_candidates']}</div><div>with source refs</div></div>
      <div class="card"><div class="num">{report['rows_with_all_ids_source_ref_candidates']}</div><div>all IDs covered</div></div>
      <div class="card"><div class="num">{report['approved_for_write_gate_count']}</div><div>approved rows</div></div>
    </section>
    <table>
      <thead><tr><th>Order</th><th>Lane</th><th>Group</th><th>Names</th><th>Source refs</th><th>Coverage</th><th>State</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </main>
</body>
</html>
"""


def write_reports(report: dict[str, Any], out_dir: Path, scorecard_path: Path | None) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "atlas_relation_identity_source_evidence_enrichment.json"
    rows_path = out_dir / "atlas_relation_identity_source_evidence_enrichment_rows.jsonl"
    md_path = out_dir / "atlas_relation_identity_source_evidence_enrichment.md"
    html_path = out_dir / "atlas_relation_identity_source_evidence_enrichment.html"
    markdown = render_markdown(report)
    write_json(json_path, report)
    write_jsonl(rows_path, report["enriched_rows"])
    md_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")
    paths = {
        "json": str(json_path),
        "rows": str(rows_path),
        "markdown": str(md_path),
        "html": str(html_path),
    }
    if scorecard_path is not None:
        scorecard_path.parent.mkdir(parents=True, exist_ok=True)
        scorecard_path.write_text(markdown, encoding="utf-8")
        paths["scorecard"] = str(scorecard_path)
    return paths


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbench", type=Path, default=DEFAULT_WORKBENCH)
    parser.add_argument("--high-risk-next-action", type=Path, default=DEFAULT_HIGH_RISK_NEXT_ACTION)
    parser.add_argument("--non-high-queue", type=Path, default=DEFAULT_NON_HIGH_QUEUE)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--no-scorecard", action="store_true")
    parser.add_argument("--per-dj-event-limit", type=int, default=4)
    parser.add_argument("--per-dj-venue-limit", type=int, default=3)
    parser.add_argument("--per-dj-collab-limit", type=int, default=4)
    parser.add_argument("--source-candidate-limit", type=int, default=12)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_report(
        workbench_path=args.workbench,
        high_risk_next_action_path=args.high_risk_next_action,
        non_high_queue_path=args.non_high_queue,
        db3_path=args.db3,
        per_dj_event_limit=args.per_dj_event_limit,
        per_dj_venue_limit=args.per_dj_venue_limit,
        per_dj_collab_limit=args.per_dj_collab_limit,
        source_candidate_limit=args.source_candidate_limit,
    )
    paths = write_reports(report, args.out_dir, None if args.no_scorecard else args.scorecard)
    if args.json_only:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "decision": report["decision"],
                    "current_story_id": report["current_story_id"],
                    "enriched_row_count": report["enriched_row_count"],
                    "rows_with_source_ref_candidates": report["rows_with_source_ref_candidates"],
                    "rows_with_all_ids_source_ref_candidates": report["rows_with_all_ids_source_ref_candidates"],
                    "ready_for_validation_count": report["ready_for_validation_count"],
                    "approved_for_write_gate_count": report["approved_for_write_gate_count"],
                    "write_gate_candidate_count": report["write_gate_candidate_count"],
                    "json": paths["json"],
                    "rows": paths["rows"],
                    "markdown": paths["markdown"],
                    "html": paths["html"],
                    "scorecard": paths.get("scorecard"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
