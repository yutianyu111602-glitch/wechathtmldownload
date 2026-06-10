#!/usr/bin/env python3
"""Classify remaining complex DB3 same-normalized identity groups after S162.

This is a report-only gate. It does not mutate DB3. It separates the remaining
same-normalized blocker into candidate write lanes and explicit blocked repair
lanes so blockers are repaired or carried forward instead of skipped.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.scripts import run_atlas_relation_identity_safe_variant_batch_s159 as s159


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S164"
SCHEMA_VERSION = "atlas_relation_identity_complex_classifier_s164.v1"

DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_complex_classifier_s164_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_COMPLEX_CLASSIFIER_S164_20260602.md"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def relation_sets(conn: sqlite3.Connection, ids: list[str]) -> dict[str, dict[str, set[str]]]:
    result = {
        "event_ids": {dj_id: set() for dj_id in ids},
        "venue_ids": {dj_id: set() for dj_id in ids},
        "source_ref_ids": {dj_id: set() for dj_id in ids},
    }
    if not ids:
        return result
    ph = ",".join("?" for _ in ids)
    for dj_id, event_id, venue_id, source_ref_id in conn.execute(
        f"""
        SELECT dj_id, event_id, venue_id, source_ref_id
        FROM dj_event
        WHERE dj_id IN ({ph})
        """,
        tuple(ids),
    ):
        key = str(dj_id)
        if event_id:
            result["event_ids"][key].add(str(event_id))
        if venue_id:
            result["venue_ids"][key].add(str(venue_id))
        if source_ref_id:
            result["source_ref_ids"][key].add(str(source_ref_id))
    return result


def common_values(values_by_id: dict[str, set[str]], ids: list[str]) -> list[str]:
    if not ids or any(not values_by_id.get(dj_id) for dj_id in ids):
        return []
    return sorted(set.intersection(*(values_by_id[dj_id] for dj_id in ids)))


def grouped_profile_rows(conn: sqlite3.Connection) -> dict[tuple[str, str], list[dict[str, Any]]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in s159.collect_profile_rows(conn):
        token = s159.normalized_token(row["normalized_name"])
        if len(token) < 2:
            continue
        city = s159.normalized_token(row["city_primary"])
        groups[(city, token)].append(row)
    return groups


def classify_row(group: list[dict[str, Any]], *, city: str, token: str, conn: sqlite3.Connection) -> dict[str, Any]:
    ids = sorted({str(row["dj_id"]) for row in group})
    reasons = s159.rejection_reasons(city, token, group)
    sets = relation_sets(conn, ids)
    common_source_refs = common_values(sets["source_ref_ids"], ids)
    common_event_ids = common_values(sets["event_ids"], ids)
    common_venue_ids = common_values(sets["venue_ids"], ids)
    displays = [str(row.get("display_name") or "") for row in sorted(group, key=s159.row_score, reverse=True)]
    shared = {
        "common_source_ref_count": len(common_source_refs),
        "common_event_count": len(common_event_ids),
        "common_venue_count": len(common_venue_ids),
        "common_source_ref_sample": common_source_refs[:8],
        "common_event_sample": common_event_ids[:8],
        "common_venue_sample": common_venue_ids[:8],
    }

    primary_lane = "blocked_other_complex"
    promotion_hint = "blocked_needs_classifier_or_source_evidence"
    ready_for_write_gate = False
    next_action = "manual_or_source_provider_review"

    if reasons == ["city_empty"] and len(group) == 2 and common_venue_ids and not common_source_refs and not common_event_ids:
        primary_lane = "candidate_cityless_common_venue_s165"
        promotion_hint = "candidate_for_guarded_db3_write_gate"
        ready_for_write_gate = True
        next_action = "run_s165_cityless_common_venue_gate"
    elif reasons == ["city_empty"] and len(group) == 2:
        primary_lane = "blocked_city_empty_no_shared_anchor"
        promotion_hint = "blocked_needs_source_or_event_or_venue_anchor"
        next_action = "acquire_source_or_provider_anchor"
    elif "risk_word_present" in reasons:
        primary_lane = "blocked_risk_word_collective_lineup_label"
        promotion_hint = "blocked_no_promotion_until_person_label_lineup_disposition"
        next_action = "label_lineup_collective_disposition_review"
    elif "group_size_not_two" in reasons:
        primary_lane = "blocked_group_size_not_two"
        promotion_hint = "blocked_needs_clustering_or_canonical_chain_gate"
        next_action = "multi_id_cluster_review"
    elif "token_not_safe_ascii" in reasons:
        primary_lane = "blocked_non_ascii_or_unsafe_token"
        promotion_hint = "blocked_needs_unicode_name_equivalence_evidence"
        next_action = "unicode_name_equivalence_review"
    elif "separator_or_collaboration_marker_present" in reasons:
        primary_lane = "blocked_separator_or_collaboration_marker"
        promotion_hint = "blocked_needs_collaboration_vs_stage_name_disposition"
        next_action = "collaboration_separator_disposition_review"
    elif "display_token_mismatch" in reasons:
        primary_lane = "blocked_display_token_mismatch"
        promotion_hint = "blocked_needs_alias_equivalence_source_evidence"
        next_action = "alias_equivalence_source_review"

    return {
        "schema_version": "atlas_relation_identity_complex_classifier_row_s164.v1",
        "current_story_id": CURRENT_STORY_ID,
        "group_id": f"{city}::{token}",
        "city_key": city,
        "identity_token": token,
        "row_count": len(group),
        "dj_ids": ids,
        "display_names": displays,
        "normalized_names": sorted({str(row.get("normalized_name") or "") for row in group}),
        "s159_rejection_reasons": reasons,
        "primary_lane": primary_lane,
        "promotion_hint": promotion_hint,
        "ready_for_write_gate": ready_for_write_gate,
        "next_action": next_action,
        **shared,
        "risk_tuple_live": [
            sum(int(row.get("event_count") or 0) for row in group),
            sum(int(row.get("venue_count") or 0) for row in group),
            sum(int(row.get("collaborator_count") or 0) for row in group),
            f"{city}::{token}",
        ],
    }


def build_report(db3_path: Path, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = s159.connect_ro(db3_path)
    try:
        rows: list[dict[str, Any]] = []
        for (city, token), group in sorted(grouped_profile_rows(conn).items()):
            ids = {str(row["dj_id"]) for row in group}
            if len(ids) <= 1:
                continue
            rows.append(classify_row(group, city=city, token=token, conn=conn))
        lane_counts = Counter(row["primary_lane"] for row in rows)
        reason_counts = Counter(reason for row in rows for reason in row["s159_rejection_reasons"])
        ready_rows = [row for row in rows if row["ready_for_write_gate"]]
        blocked_rows = [row for row in rows if not row["ready_for_write_gate"]]
        report = {
            "schema_version": SCHEMA_VERSION,
            "current_story_id": CURRENT_STORY_ID,
            "generated_at": now_iso(),
            "decision": "atlas_relation_identity_complex_classifier_s164_ready_report_only",
            "source_inputs": {"db3": rel_path(db3_path)},
            "counts": {
                "total_same_normalized_groups": len(rows),
                "ready_for_write_gate_count": len(ready_rows),
                "blocked_count": len(blocked_rows),
                "lane_counts": dict(lane_counts),
                "s159_rejection_reason_counts": dict(reason_counts),
            },
            "next_recommended_story": "S165" if ready_rows else "S164B",
            "next_recommended_action": (
                "run cityless common-venue guarded DB3 write gate for 23 candidate groups"
                if lane_counts.get("candidate_cityless_common_venue_s165")
                else "collect source/provider evidence for blocked complex groups"
            ),
            "safety": {
                "report_only": True,
                "database_mutations": False,
                "db2_projection": False,
                "release_rebuild": False,
                "deploy_upload_review": False,
                "provider_or_llm_call": False,
                "secret_read": False,
                "service_restart": False,
                "broad_disk_scan": False,
            },
            "samples": {
                lane: [row for row in rows if row["primary_lane"] == lane][:10]
                for lane in sorted(lane_counts)
            },
            "artifacts": {
                "rows_jsonl": rel_path(out_dir / "complex_identity_rows_s164.jsonl"),
                "ready_rows_jsonl": rel_path(out_dir / "complex_identity_ready_for_write_gate_s164.jsonl"),
                "blocked_rows_jsonl": rel_path(out_dir / "complex_identity_blocked_rows_s164.jsonl"),
                "tasks_jsonl": rel_path(out_dir / "complex_identity_tasks_s164.jsonl"),
            },
        }
        tasks = [
            {
                "task_id": f"s164:{row['primary_lane']}:{index + 1:04d}",
                "group_id": row["group_id"],
                "next_action": row["next_action"],
                "promotion_hint": row["promotion_hint"],
                "ready_for_write_gate": row["ready_for_write_gate"],
                "dj_ids": row["dj_ids"],
            }
            for index, row in enumerate(rows)
        ]
        write_jsonl(out_dir / "complex_identity_rows_s164.jsonl", rows)
        write_jsonl(out_dir / "complex_identity_ready_for_write_gate_s164.jsonl", ready_rows)
        write_jsonl(out_dir / "complex_identity_blocked_rows_s164.jsonl", blocked_rows)
        write_jsonl(out_dir / "complex_identity_tasks_s164.jsonl", tasks)
        return report
    finally:
        conn.close()


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    counts = report["counts"]
    lines = [
        "# Weekly Atlas Relation Identity Complex Classifier S164",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Total same-normalized groups: `{counts['total_same_normalized_groups']}`",
        f"- Ready for write gate: `{counts['ready_for_write_gate_count']}`",
        f"- Blocked: `{counts['blocked_count']}`",
        f"- Next recommended story: `{report['next_recommended_story']}`",
        f"- Next recommended action: `{report['next_recommended_action']}`",
        "",
        "## Lane Counts",
        "",
    ]
    for lane, count in sorted(counts["lane_counts"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- `{lane}`: `{count}`")
    lines.extend(["", "## Rejection Reason Counts", ""])
    for reason, count in sorted(counts["s159_rejection_reason_counts"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- `{reason}`: `{count}`")
    lines.extend(["", "## Safety", ""])
    lines.append("- Report-only classifier. No DB1/DB2/DB3 mutation, DB2 projection, deploy, upload, review, model/API call, secret read, service restart, or broad disk scan.")
    lines.append("")
    atomic_write_text(path, "\n".join(lines))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(args.db3, args.out_dir)
    json_path = args.out_dir / "atlas_relation_identity_complex_classifier_s164.json"
    md_path = args.out_dir / "atlas_relation_identity_complex_classifier_s164.md"
    atomic_write_json(json_path, report)
    write_markdown(md_path, report)
    if args.scorecard:
        write_markdown(args.scorecard, report)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "total_same_normalized_groups": report["counts"]["total_same_normalized_groups"],
                "ready_for_write_gate_count": report["counts"]["ready_for_write_gate_count"],
                "blocked_count": report["counts"]["blocked_count"],
                "next_recommended_story": report["next_recommended_story"],
                "json": str(json_path),
                "markdown": str(md_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
