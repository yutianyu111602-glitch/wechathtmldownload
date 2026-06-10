#!/usr/bin/env python3
"""Build S185 source/provider acquisition workbench for remaining DB3 identity blockers.

S185 consumes the post-S183 remaining same-normalized groups and enriches each
group with DB3 source/event/provider context. It does not fetch network
resources and does not mutate DB1/DB2/DB3. Its main output is a bounded S186
candidate lane for two-profile variants backed by the same source account plus
same source title or same event title.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_source_anchor_batch_s167 as s167


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S185"
SCHEMA_VERSION = "atlas_relation_identity_source_provider_acquisition_s185.v1"

DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_INPUT = (
    REPORTS_ROOT
    / "atlas_relation_identity_compound_disposition_s185_after_s183_dryrun_20260602"
    / "compound_disposition_remaining_rows_s183.jsonl"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_source_provider_acquisition_s185_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_SOURCE_PROVIDER_ACQUISITION_S185_20260602.md"

SECRET_LIKE_RE = re.compile(r"(cookie|authorization|x-auth-key|api[_-]?key|secret|bearer\s+[a-z0-9._-]+)", re.I)
S186_ALLOWED_REASONS = {"city_empty", "token_not_safe_ascii", "display_token_mismatch"}


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


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"expected object JSONL row: {path}")
        rows.append(value)
    return rows


def iter_string_values(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_string_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_string_values(item)


def compact_values(row: dict[str, Any]) -> set[str]:
    values = [
        *list(row.get("display_names") or []),
        *list(row.get("normalized_names") or []),
        row.get("identity_token") or "",
    ]
    return s167.compact_set(values)


def limited(values: list[str], limit: int) -> list[str]:
    return values[:limit]


def fetch_profile_event_context(conn: sqlite3.Connection, dj_id: str, *, sample_limit: int) -> dict[str, Any]:
    events = [
        dict(row)
        for row in conn.execute(
            """
            SELECT
              e.dj_id,
              e.event_id,
              e.event_title,
              e.venue_id,
              e.venue_name,
              e.city,
              e.starts_at,
              e.source_ref_id,
              s.source_account,
              s.source_title,
              s.post_date,
              s.source_kind
            FROM dj_event e
            LEFT JOIN source_ref s ON s.source_ref_id = e.source_ref_id
            WHERE e.dj_id = ?
            ORDER BY COALESCE(e.starts_at, ''), COALESCE(e.event_id, ''), COALESCE(e.source_ref_id, '')
            """,
            (dj_id,),
        )
    ]
    profile = conn.execute(
        """
        SELECT dj_id, display_name, normalized_name, aliases_json, city_primary,
               event_count, venue_count, collaborator_count
        FROM dj_profile
        WHERE dj_id = ?
        """,
        (dj_id,),
    ).fetchone()
    profile_dict = dict(profile) if profile else {"dj_id": dj_id}
    source_ref_ids = sorted({str(event["source_ref_id"]) for event in events if event.get("source_ref_id")})
    source_accounts = sorted({str(event["source_account"]) for event in events if event.get("source_account")})
    source_titles = sorted({str(event["source_title"]) for event in events if event.get("source_title")})
    event_titles = sorted({str(event["event_title"]) for event in events if event.get("event_title")})
    venue_ids = sorted({str(event["venue_id"]) for event in events if event.get("venue_id")})
    venue_names = sorted({str(event["venue_name"]) for event in events if event.get("venue_name")})
    cities = sorted({str(event["city"]) for event in events if event.get("city")})
    return {
        "profile": profile_dict,
        "event_sample": events[: min(sample_limit, 8)],
        "source_ref_ids": limited(source_ref_ids, sample_limit),
        "source_accounts": limited(source_accounts, sample_limit),
        "source_titles": limited(source_titles, sample_limit),
        "event_titles": limited(event_titles, sample_limit),
        "venue_ids": limited(venue_ids, sample_limit),
        "venue_names": limited(venue_names, sample_limit),
        "cities": limited(cities, sample_limit),
        "_source_ref_ids_all": source_ref_ids,
        "_source_accounts_all": source_accounts,
        "_source_titles_all": source_titles,
        "_event_titles_all": event_titles,
        "_venue_ids_all": venue_ids,
        "_venue_names_all": venue_names,
        "_cities_all": cities,
        "event_sample_count": len(events),
    }


def common_values(contexts: list[dict[str, Any]], key: str) -> list[str]:
    all_key = f"_{key}_all"
    sets = [set(context.get(all_key) or context.get(key) or []) for context in contexts]
    if not sets or any(not value_set for value_set in sets):
        return []
    return sorted(set.intersection(*sets))


def public_context(context: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in context.items() if not key.startswith("_")}


def classify_enriched_row(row: dict[str, Any], contexts: list[dict[str, Any]], intersections: dict[str, list[str]]) -> str:
    row_count = int(row.get("row_count") or len(row.get("dj_ids") or []))
    compacts = compact_values(row)
    risk_reasons = list(row.get("s183_risk_reasons") or [])
    lane = str(row.get("s183_lane") or "")
    common_account = bool(intersections["common_source_accounts"])
    common_source_title = bool(intersections["common_source_titles"])
    common_event_title = bool(intersections["common_event_titles"])
    common_source_ref = bool(intersections["common_source_ref_ids"])
    common_venue = bool(intersections["common_venue_ids"] or intersections["common_venue_names"])
    has_all_context = all(context.get("event_sample_count", 0) > 0 for context in contexts)
    allowed_s186_reasons = set(row.get("s159_rejection_reasons") or []) <= S186_ALLOWED_REASONS

    if (
        lane == "source_provider_acquisition_no_anchor"
        and row_count == 2
        and len(compacts) == 1
        and not risk_reasons
        and allowed_s186_reasons
        and common_account
        and (common_source_title or common_event_title)
        and has_all_context
    ):
        return "source_title_event_pair_write_gate_candidate"
    if (
        lane == "source_provider_acquisition_no_anchor"
        and row_count == 2
        and len(compacts) == 1
        and common_account
        and (common_source_title or common_event_title)
        and has_all_context
    ):
        return "alias_or_risk_manual_review"
    if common_source_ref and not risk_reasons:
        return "common_source_ref_manual_gate_candidate"
    if "provider_crosscheck" in lane and common_account and common_venue:
        return "provider_crosscheck_ready"
    if "cluster" in lane and common_account and (common_source_title or common_event_title or common_venue):
        return "cluster_chain_evidence_ready"
    if "compound_or_alias" in lane:
        return "compound_or_alias_manual_review"
    if not has_all_context:
        return "source_context_missing"
    return "external_or_manual_acquisition_required"


def allowed_weapon_chain(route: str) -> list[dict[str, str]]:
    common = [
        {
            "tool": "db3_readonly_sqlite",
            "purpose": "Read source_ref/event/provider evidence in DB3 only.",
            "mode": "read_only",
        },
        {
            "tool": "jsonl_spool",
            "purpose": "Carry candidate rows into the next single-writer gate.",
            "mode": "report_local",
        },
    ]
    if route == "source_title_event_pair_write_gate_candidate":
        return [
            *common,
            {
                "tool": "s186_db3_source_title_event_pair_write_gate",
                "purpose": "DB3-only identity merge after lock, backup, transaction, redirect, and readback.",
                "mode": "write_gate_required",
            },
        ]
    if route in {"provider_crosscheck_ready", "cluster_chain_evidence_ready"}:
        return [
            *common,
            {
                "tool": "provider_crosscheck_workbench",
                "purpose": "Require same venue/provider/date/title evidence before any later write gate.",
                "mode": "no_write",
            },
        ]
    return [
        *common,
        {
            "tool": "openclaw_or_db2_weapons_layer",
            "purpose": "Only after DB3 evidence is insufficient; use Docker resident weapon profiles and JSONL spool.",
            "mode": "bounded_acquisition",
        },
    ]


def build_workbench(
    *,
    db3_path: Path,
    input_path: Path,
    out_dir: Path,
    scorecard_path: Path,
    sample_limit: int,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = read_jsonl(input_path)
    conn = sqlite3.connect(f"file:{db3_path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    enriched: list[dict[str, Any]] = []
    try:
        for index, row in enumerate(rows, start=1):
            contexts = [fetch_profile_event_context(conn, str(dj_id), sample_limit=sample_limit) for dj_id in row.get("dj_ids") or []]
            intersections = {
                "common_source_ref_ids": common_values(contexts, "source_ref_ids"),
                "common_source_accounts": common_values(contexts, "source_accounts"),
                "common_source_titles": common_values(contexts, "source_titles"),
                "common_event_titles": common_values(contexts, "event_titles"),
                "common_venue_ids": common_values(contexts, "venue_ids"),
                "common_venue_names": common_values(contexts, "venue_names"),
                "common_cities": common_values(contexts, "cities"),
            }
            route = classify_enriched_row(row, contexts, intersections)
            enriched.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "current_story_id": CURRENT_STORY_ID,
                    "row_index": index,
                    "group_id": row.get("group_id"),
                    "source_group_row": row,
                    "dj_ids": row.get("dj_ids") or [],
                    "display_names": row.get("display_names") or [],
                    "s183_lane": row.get("s183_lane"),
                    "s185_route": route,
                    "s185_ready_for_s186_write_gate": route == "source_title_event_pair_write_gate_candidate",
                    "unicode_compact_values": sorted(compact_values(row)),
                    "common_evidence": intersections,
                    "per_dj_context": [public_context(context) for context in contexts],
                    "acceptance_requirements_before_write": [
                        "exactly_two_profiles",
                        "one_unicode_compact_token",
                        "no_s183_risk_reasons",
                        "same_source_account",
                        "same_source_title_or_same_event_title",
                        "single_writer_lock",
                        "db3_backup",
                        "BEGIN_IMMEDIATE_transaction",
                        "postwrite_readback",
                        "no_empty_overwrite",
                        "source_ref_preservation",
                    ],
                    "allowed_weapon_chain": allowed_weapon_chain(route),
                }
            )
    finally:
        conn.close()

    route_counts = Counter(row["s185_route"] for row in enriched)
    lane_counts = Counter(str(row.get("s183_lane") or "") for row in enriched)
    s186_candidates = [row for row in enriched if row["s185_ready_for_s186_write_gate"]]
    provider_rows = [row for row in enriched if row["s185_route"] == "provider_crosscheck_ready"]
    cluster_rows = [row for row in enriched if row["s185_route"] == "cluster_chain_evidence_ready"]
    review_rows = [
        row
        for row in enriched
        if row["s185_route"] in {"compound_or_alias_manual_review", "common_source_ref_manual_gate_candidate", "alias_or_risk_manual_review"}
    ]
    external_rows = [row for row in enriched if row["s185_route"] in {"external_or_manual_acquisition_required", "source_context_missing"}]
    tasks = [
        {
            "task_id": f"s185:{row['s185_route']}:{idx + 1:04d}",
            "task_type": row["s185_route"],
            "group_id": row["group_id"],
            "dj_ids": row["dj_ids"],
            "display_names": row["display_names"],
            "ready_for_s186_write_gate": row["s185_ready_for_s186_write_gate"],
            "next_action": (
                "run_s186_source_title_event_pair_db3_write_gate"
                if row["s185_ready_for_s186_write_gate"]
                else "continue_source_provider_or_manual_identity_review"
            ),
        }
        for idx, row in enumerate(enriched)
    ]

    artifacts = {
        "report_json": rel_path(out_dir / "atlas_relation_identity_source_provider_acquisition_s185.json"),
        "scorecard": rel_path(scorecard_path),
        "workbench_jsonl": rel_path(out_dir / "source_provider_acquisition_workbench_s185.jsonl"),
        "s186_candidates_jsonl": rel_path(out_dir / "source_title_event_pair_candidates_s185.jsonl"),
        "provider_crosscheck_jsonl": rel_path(out_dir / "provider_crosscheck_rows_s185.jsonl"),
        "cluster_chain_jsonl": rel_path(out_dir / "cluster_chain_rows_s185.jsonl"),
        "review_rows_jsonl": rel_path(out_dir / "manual_review_rows_s185.jsonl"),
        "external_acquisition_rows_jsonl": rel_path(out_dir / "external_or_manual_acquisition_rows_s185.jsonl"),
        "tasks_jsonl": rel_path(out_dir / "relation_identity_source_provider_acquisition_tasks_s185.jsonl"),
    }
    value_probe = "\n".join(iter_string_values(enriched[:10]))
    secret_like_findings = sorted(set(SECRET_LIKE_RE.findall(value_probe)))
    decision = (
        "atlas_relation_identity_source_provider_acquisition_s185_ready_for_s186_gate"
        if s186_candidates and not secret_like_findings
        else "atlas_relation_identity_source_provider_acquisition_s185_blocked_report_only"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "current_story_id": CURRENT_STORY_ID,
        "generated_at": now_iso(),
        "decision": decision,
        "input_path": rel_path(input_path),
        "db3_path": rel_path(db3_path),
        "artifacts": artifacts,
        "counts": {
            "input_group_count": len(rows),
            "workbench_row_count": len(enriched),
            "s186_candidate_count": len(s186_candidates),
            "provider_crosscheck_ready_count": len(provider_rows),
            "cluster_chain_evidence_ready_count": len(cluster_rows),
            "manual_review_count": len(review_rows),
            "external_or_manual_acquisition_count": len(external_rows),
            "route_counts": dict(sorted(route_counts.items())),
            "s183_lane_counts": dict(sorted(lane_counts.items())),
        },
        "safety": {
            "database_mutations": False,
            "db2_projection": False,
            "deploy_upload_review": False,
            "network_fetch": False,
            "model_calls": False,
            "secret_values_printed": False,
            "secret_like_findings": secret_like_findings,
        },
        "next_action": {
            "story": "S186",
            "summary": "Run DB3-only source-title/event-title pair write gate for S185 candidates, then rerun relation audit/preflight.",
            "input": artifacts["s186_candidates_jsonl"],
        },
    }

    write_jsonl(out_dir / "source_provider_acquisition_workbench_s185.jsonl", enriched)
    write_jsonl(out_dir / "source_title_event_pair_candidates_s185.jsonl", s186_candidates)
    write_jsonl(out_dir / "provider_crosscheck_rows_s185.jsonl", provider_rows)
    write_jsonl(out_dir / "cluster_chain_rows_s185.jsonl", cluster_rows)
    write_jsonl(out_dir / "manual_review_rows_s185.jsonl", review_rows)
    write_jsonl(out_dir / "external_or_manual_acquisition_rows_s185.jsonl", external_rows)
    write_jsonl(out_dir / "relation_identity_source_provider_acquisition_tasks_s185.jsonl", tasks)
    atomic_write_json(out_dir / "atlas_relation_identity_source_provider_acquisition_s185.json", report)
    write_scorecard(scorecard_path, report)
    return report


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    counts = report["counts"]
    lines = [
        "# Weekly Atlas Relation Identity Source/Provider Acquisition S185",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Input groups: `{counts['input_group_count']}`",
        f"- S186 source-title/event pair candidates: `{counts['s186_candidate_count']}`",
        f"- Provider crosscheck ready: `{counts['provider_crosscheck_ready_count']}`",
        f"- Cluster chain evidence ready: `{counts['cluster_chain_evidence_ready_count']}`",
        f"- Manual review rows: `{counts['manual_review_count']}`",
        f"- External/manual acquisition rows: `{counts['external_or_manual_acquisition_count']}`",
        f"- Route counts: `{json.dumps(counts['route_counts'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Boundaries",
        "",
        "- Read-only DB3 source/provider/event context enrichment.",
        "- No DB1/DB2/DB3 mutation, no DB2 projection, no deploy/upload/review, no network fetch, no model call, no cookie/token/API key value output.",
        "- S186 may only consume `source_title_event_pair_candidates_s185.jsonl` through a separate single-writer write gate with backup and postwrite readback.",
        "",
        "## Artifacts",
    ]
    for key, value in report["artifacts"].items():
        lines.append(f"- `{key}`: `{value}`")
    atomic_write_text(path, "\n".join(lines) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--sample-limit", type=int, default=80)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_workbench(
        db3_path=args.db3,
        input_path=args.input,
        out_dir=args.out_dir,
        scorecard_path=args.scorecard,
        sample_limit=args.sample_limit,
    )
    print(json.dumps({"decision": report["decision"], "counts": report["counts"], "out_dir": rel_path(args.out_dir)}, ensure_ascii=False))
    return 0 if report["safety"]["secret_like_findings"] == [] else 2


if __name__ == "__main__":
    raise SystemExit(main())
