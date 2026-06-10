#!/usr/bin/env python3
"""Build S190 external/manual acquisition queues for relation identity blockers.

S190 is report-only. It consumes the fresh S185 external/manual acquisition
JSONL after S189 and splits it into bounded public-evidence queues for the
Docker resident DB2 weapons control plane. It does not fetch the network and
does not mutate DB1/DB2/DB3.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.scripts import build_atlas_relation_identity_source_provider_acquisition_s185 as s185
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_source_anchor_batch_s167 as s167


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S190"
REPORT_STEM = "atlas_relation_external_acquisition_queue_s190"
SCHEMA_VERSION = f"{REPORT_STEM}.v1"

DEFAULT_INPUT = (
    REPORTS_ROOT
    / "atlas_relation_identity_source_provider_acquisition_s190_after_s189_fresh_20260602"
    / "external_or_manual_acquisition_rows_s185.jsonl"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_external_acquisition_queue_s190_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_EXTERNAL_ACQUISITION_QUEUE_S190_20260602.md"

PUBLIC_EVIDENCE_SCHEMA = [
    "evidence_url",
    "final_url",
    "http_status",
    "fetched_at",
    "content_hash",
    "page_title",
    "matched_names",
    "matched_source_account",
    "matched_event_title",
    "matched_date",
    "matched_venue",
    "matched_city",
    "platform",
    "confidence",
    "raw_cache_path",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel_path(path: Path) -> str:
    return s167.rel_path(path)


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


def values_from_contexts(row: dict[str, Any], field: str) -> list[str]:
    sets: list[set[str]] = []
    for context in row.get("per_dj_context") or []:
        values = {str(value) for value in context.get(field) or [] if str(value).strip()}
        sets.append(values)
    if not sets or any(not values for values in sets):
        return []
    return sorted(set.intersection(*sets))


def dates_from_contexts(row: dict[str, Any], field: str) -> list[str]:
    sets: list[set[str]] = []
    for context in row.get("per_dj_context") or []:
        values = {
            str(event.get(field))
            for event in context.get("event_sample") or []
            if str(event.get(field) or "").strip()
        }
        sets.append(values)
    if not sets or any(not values for values in sets):
        return []
    return sorted(set.intersection(*sets))


def best_seed_events(row: dict[str, Any], limit: int = 5) -> list[dict[str, str]]:
    seeds: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for context in row.get("per_dj_context") or []:
        for event in context.get("event_sample") or []:
            item = {
                "source_account": str(event.get("source_account") or ""),
                "source_title": str(event.get("source_title") or ""),
                "event_title": str(event.get("event_title") or ""),
                "starts_at": str(event.get("starts_at") or ""),
                "post_date": str(event.get("post_date") or ""),
                "venue_name": str(event.get("venue_name") or ""),
                "city": str(event.get("city") or ""),
                "source_ref_id": str(event.get("source_ref_id") or ""),
            }
            key = (item["source_account"], item["source_title"], item["event_title"], item["starts_at"])
            if key in seen:
                continue
            if any(item.values()):
                seeds.append(item)
                seen.add(key)
            if len(seeds) >= limit:
                return seeds
    return seeds


def every_profile_has_title_seed(row: dict[str, Any]) -> bool:
    return all((context.get("source_titles") or context.get("event_titles")) for context in row.get("per_dj_context") or [])


def every_profile_has_date_seed(row: dict[str, Any]) -> bool:
    return all(
        any(str(event.get("starts_at") or event.get("post_date") or "").strip() for event in context.get("event_sample") or [])
        for context in row.get("per_dj_context") or []
    )


def route_row(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    common = row.get("common_evidence") or {}
    common_accounts = sorted(set(common.get("common_source_accounts") or values_from_contexts(row, "source_accounts")))
    common_source_titles = sorted(set(common.get("common_source_titles") or values_from_contexts(row, "source_titles")))
    common_event_titles = sorted(set(common.get("common_event_titles") or values_from_contexts(row, "event_titles")))
    common_venues = sorted(set((common.get("common_venue_names") or []) + (common.get("common_venue_ids") or []) + values_from_contexts(row, "venue_names") + values_from_contexts(row, "venue_ids")))
    common_cities = sorted(set(common.get("common_cities") or values_from_contexts(row, "cities")))
    common_starts_at = dates_from_contexts(row, "starts_at")
    common_post_dates = dates_from_contexts(row, "post_date")
    source_group = row.get("source_group_row") or {}
    lane = str(row.get("s183_lane") or source_group.get("s183_lane") or "")
    has_title = bool(common_source_titles or common_event_titles)
    has_date = bool(common_starts_at or common_post_dates)
    has_account = bool(common_accounts)
    has_title_seed = every_profile_has_title_seed(row)
    has_date_seed = every_profile_has_date_seed(row)

    if lane == "cluster_chain_review":
        route = "S190D_cluster_chain_bridge"
    elif has_account and (has_title or has_title_seed) and (has_date or has_date_seed):
        route = "S190A_high_priority_public_evidence"
    elif has_account and (has_title or has_title_seed):
        route = "S190B_title_without_date"
    else:
        route = "S190F_manual_seed_needed"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "current_story_id": CURRENT_STORY_ID,
        "route": route,
        "task_id": f"s190:{route}:{source_group.get('group_id') or row.get('group_id')}",
        "group_id": row.get("group_id"),
        "dj_ids": row.get("dj_ids") or [],
        "display_names": row.get("display_names") or [],
        "unicode_compact_values": row.get("unicode_compact_values") or [],
        "s183_lane": lane,
        "s185_route": row.get("s185_route"),
        "row_count": source_group.get("row_count"),
        "common_public_anchors": {
            "source_accounts": common_accounts,
            "source_titles": common_source_titles,
            "event_titles": common_event_titles,
            "starts_at": common_starts_at,
            "post_dates": common_post_dates,
            "venues": common_venues,
            "cities": common_cities,
        },
        "seed_events": best_seed_events(row),
        "seed_coverage": {
            "every_profile_has_title_seed": has_title_seed,
            "every_profile_has_date_seed": has_date_seed,
            "has_common_title": has_title,
            "has_common_date": has_date,
        },
        "next_gate": (
            "S191_bounded_no_cookie_public_crawl_canary"
            if route in {"S190A_high_priority_public_evidence", "S190D_cluster_chain_bridge"}
            else "manual_or_provider_crosscheck_before_crawl"
        ),
        "write_authorization": {
            "db1_mutation": False,
            "db2_mutation": False,
            "db3_mutation": False,
            "db2_projection": False,
            "deploy_upload_review_release": False,
        },
    }
    return route, payload


def weapon_plan() -> dict[str, Any]:
    return {
        "control_plane": "Docker resident layered DB2 weapons + external-link-db2-arsenal skill",
        "profiles": ["db2-light-workers", "db2-browser-tools", "db2-reconcile", "db2-writer"],
        "commands": [
            "python tools/stage7_rewrite/scripts/db2ctl.py status",
            "python tools/stage7_rewrite/scripts/db2ctl.py health --lock-holders",
            "python tools/stage7_rewrite/scripts/db2ctl.py up safe --worker outlink_expand_linktree",
            "python tools/stage7_rewrite/scripts/db2ctl.py up safe --worker outlink_expand_shorturl",
        ],
        "spool_contract": {
            "workers_write": "JSONL shards plus raw-local cache only",
            "atomicity": "worker writes temp shard, then atomic rename into ready/",
            "idempotency_key": "group_id + sorted(dj_ids) + source_ref_id/evidence_url + content_hash",
            "single_writer": "Only db2-writer may open DB2/sidecar for writes after lock/backup/readback.",
        },
        "live_db2_location_rule": "Keep live DB2 on WSL ext4; do not run high-frequency live DB2 writes on D:.",
    }


def build_queue(input_path: Path, out_dir: Path, scorecard_path: Path, *, s191_a_limit: int, s191_d_limit: int) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = s185.read_jsonl(input_path)
    routed: dict[str, list[dict[str, Any]]] = {
        "S190A_high_priority_public_evidence": [],
        "S190B_title_without_date": [],
        "S190D_cluster_chain_bridge": [],
        "S190F_manual_seed_needed": [],
    }
    for row in rows:
        route, payload = route_row(row)
        routed[route].append(payload)
    s191_canary = [
        *routed["S190A_high_priority_public_evidence"][:s191_a_limit],
        *routed["S190D_cluster_chain_bridge"][:s191_d_limit],
    ]
    route_counts = {route: len(items) for route, items in routed.items()}
    report_path = out_dir / f"{REPORT_STEM}.json"
    report = {
        "schema_version": SCHEMA_VERSION,
        "current_story_id": CURRENT_STORY_ID,
        "generated_at": now_iso(),
        "decision": "atlas_relation_external_acquisition_queue_s190_ready_report_only",
        "input_path": rel_path(input_path),
        "counts": {
            "input_row_count": len(rows),
            "route_counts": route_counts,
            "s191_canary_count": len(s191_canary),
        },
        "public_evidence_schema": PUBLIC_EVIDENCE_SCHEMA,
        "weapon_plan": weapon_plan(),
        "safety": {
            "report_only": True,
            "network_fetch": False,
            "database_mutations": False,
            "db1_mutation": False,
            "db2_mutation": False,
            "db3_mutation": False,
            "db2_projection": False,
            "deploy_upload_review_release": False,
            "cookie_token_secret_read": False,
            "secret_values_printed": False,
        },
        "samples": {route: items[:5] for route, items in routed.items()},
        "artifacts": {
            "report_json": rel_path(report_path),
            "scorecard": rel_path(scorecard_path),
            "s190a_jsonl": rel_path(out_dir / "s190a_high_priority_public_evidence.jsonl"),
            "s190b_jsonl": rel_path(out_dir / "s190b_title_without_date.jsonl"),
            "s190d_jsonl": rel_path(out_dir / "s190d_cluster_chain_bridge.jsonl"),
            "s190f_jsonl": rel_path(out_dir / "s190f_manual_seed_needed.jsonl"),
            "s191_canary_jsonl": rel_path(out_dir / "s191_bounded_no_cookie_public_crawl_canary_queue.jsonl"),
        },
    }
    write_jsonl(out_dir / "s190a_high_priority_public_evidence.jsonl", routed["S190A_high_priority_public_evidence"])
    write_jsonl(out_dir / "s190b_title_without_date.jsonl", routed["S190B_title_without_date"])
    write_jsonl(out_dir / "s190d_cluster_chain_bridge.jsonl", routed["S190D_cluster_chain_bridge"])
    write_jsonl(out_dir / "s190f_manual_seed_needed.jsonl", routed["S190F_manual_seed_needed"])
    write_jsonl(out_dir / "s191_bounded_no_cookie_public_crawl_canary_queue.jsonl", s191_canary)
    atomic_write_json(report_path, report)
    write_scorecard(scorecard_path, report)
    return report


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    counts = report["counts"]
    route_counts = counts["route_counts"]
    lines = [
        "# Weekly Atlas Relation External Acquisition Queue S190",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Input rows: `{counts['input_row_count']}`",
        f"- S190A high-priority public evidence: `{route_counts.get('S190A_high_priority_public_evidence', 0)}`",
        f"- S190B title without date: `{route_counts.get('S190B_title_without_date', 0)}`",
        f"- S190D cluster-chain bridge: `{route_counts.get('S190D_cluster_chain_bridge', 0)}`",
        f"- S190F manual seed needed: `{route_counts.get('S190F_manual_seed_needed', 0)}`",
        f"- S191 canary queue: `{counts['s191_canary_count']}`",
        "",
        "## Boundaries",
        "",
        "- Report-only queue compiler. No network fetch, no DB1/DB2/DB3 write, no DB2 projection, no deploy/upload/review/release.",
        "- S191 must run through Docker resident weapons, JSONL spool, raw-local cache, and single db2-writer gates.",
        "- Cookie/token/secret values are not read or printed.",
        "",
        "## Public Evidence Schema",
        "",
        ", ".join(f"`{field}`" for field in report["public_evidence_schema"]),
        "",
        "## Artifacts",
    ]
    for key, value in report["artifacts"].items():
        lines.append(f"- `{key}`: `{value}`")
    atomic_write_text(path, "\n".join(lines) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--s191-a-limit", type=int, default=20)
    parser.add_argument("--s191-d-limit", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_queue(
        args.input,
        args.out_dir,
        args.scorecard,
        s191_a_limit=args.s191_a_limit,
        s191_d_limit=args.s191_d_limit,
    )
    print(json.dumps({"decision": report["decision"], "counts": report["counts"], "out_dir": rel_path(args.out_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
