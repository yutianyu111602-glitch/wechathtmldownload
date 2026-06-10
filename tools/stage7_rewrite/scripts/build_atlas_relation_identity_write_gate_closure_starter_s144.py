#!/usr/bin/env python3
"""Build a report-only closure starter for the Atlas relation identity write gate.

S144 consumes the full S141 recommendation/evidence packets and turns them into
an auditable next-action contract. It intentionally does not approve or execute
any DB3 identity write.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_RECOMMENDATION = (
    REPORTS_ROOT
    / "atlas_relation_identity_disposition_recommendation_s141_full_20260602"
    / "atlas_relation_identity_disposition_recommendation_s140.json"
)
DEFAULT_EVIDENCE = (
    REPORTS_ROOT
    / "atlas_relation_identity_source_evidence_enrichment_s141_full_20260602"
    / "atlas_relation_identity_source_evidence_enrichment.json"
)
DEFAULT_BLOCKER = (
    REPORTS_ROOT
    / "atlas_relation_identity_write_blocker_audit_s141_full_20260602"
    / "atlas_relation_identity_write_blocker_audit.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_write_gate_closure_starter_s144_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_WRITE_GATE_CLOSURE_STARTER_S144_20260602.md"
CURRENT_STORY_ID = "S144"
SCHEMA_VERSION = "atlas_relation_identity_write_gate_closure_starter.v1"

MERGE_CANDIDATE = "merge_candidate_needs_human_signoff"
NEEDS_EVIDENCE = "needs_more_evidence"
COLLECTIVE_EXCLUDE = "collective_or_lineup_not_dj"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


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


def compact_row(row: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "recommendation_row_id": row.get("recommendation_row_id", ""),
        "workbench_row_id": row.get("workbench_row_id", ""),
        "review_order": row.get("review_order"),
        "lane": row.get("lane"),
        "risk_level": row.get("risk_level"),
        "group_id": row.get("group_id"),
        "city_key": row.get("city_key"),
        "display_names": as_list(row.get("display_names")),
        "canonical_dj_id": row.get("canonical_dj_id"),
        "merge_dj_ids": as_list(row.get("merge_dj_ids")),
        "all_dj_ids": as_list(row.get("all_dj_ids")),
        "source_ref_candidate_count": int(row.get("source_ref_candidate_count") or 0),
        "all_ids_source_ref_coverage": row.get("all_ids_source_ref_coverage") or {},
        "recommendation": row.get("recommendation"),
        "recommendation_rationale": row.get("recommendation_rationale", ""),
        "review_flags": as_list(row.get("review_flags")),
        "suggested_disposition": row.get("suggested_disposition", ""),
        "closure_status": status,
        "ready_for_validation": False,
        "approved_for_write_gate": False,
        "write_gate_candidate": False,
        "database_write_allowed": False,
    }


def sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            int(row.get("review_order") or 999999),
            str(row.get("group_id") or ""),
            str(row.get("recommendation_row_id") or ""),
        ),
    )


def split_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {
        MERGE_CANDIDATE: [],
        NEEDS_EVIDENCE: [],
        COLLECTIVE_EXCLUDE: [],
    }
    for row in rows:
        recommendation = str(row.get("recommendation") or "")
        if recommendation == MERGE_CANDIDATE:
            buckets[MERGE_CANDIDATE].append(compact_row(row, "pending_human_approved_disposition"))
        elif recommendation == COLLECTIVE_EXCLUDE:
            buckets[COLLECTIVE_EXCLUDE].append(compact_row(row, "excluded_from_identity_merge"))
        else:
            buckets[NEEDS_EVIDENCE].append(compact_row(row, "evidence_acquisition_required"))
    return {key: sort_rows(value) for key, value in buckets.items()}


def source_coverage_ok(row: dict[str, Any]) -> bool:
    coverage = row.get("all_ids_source_ref_coverage") or {}
    try:
        return int(coverage.get("all_ids") or 0) > 0 and int(coverage.get("all_ids") or 0) == int(
            coverage.get("with_source_ref") or 0
        )
    except (TypeError, ValueError):
        return False


def build_candidate_slice(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["source_ref_coverage_complete"] = source_coverage_ok(row)
        item["can_enter_write_gate_now"] = False
        item["blocked_reason"] = "human_approved_disposition_missing"
        item["required_before_write_gate"] = [
            "human_approved_disposition",
            "source_ref_or_original_url_per_identity_variant",
            "identity_match_notes",
            "field_preservation_notes",
            "single_writer_lock_contract",
            "backup_and_rollback_contract",
            "postwrite_readback_contract",
        ]
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def action_tasks(buckets: dict[str, list[dict[str, Any]]], candidate_slice: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "task_id": "s144:human_signoff_for_merge_candidates",
            "requirement_id": "relation_identity_write_gate",
            "status": "blocked_pending_human_approved_disposition",
            "hard_blocking": True,
            "detail": {"row_count": len(buckets[MERGE_CANDIDATE]), "starter_slice_count": len(candidate_slice)},
        },
        {
            "task_id": "s144:evidence_acquisition_for_needs_more_evidence",
            "requirement_id": "relation_identity_write_gate",
            "status": "blocked_pending_source_evidence_acquisition",
            "hard_blocking": True,
            "detail": {"row_count": len(buckets[NEEDS_EVIDENCE])},
        },
        {
            "task_id": "s144:exclude_collective_or_lineup_rows",
            "requirement_id": "relation_identity_write_gate",
            "status": "closed_without_merge_pending_no_write_disposition_record",
            "hard_blocking": True,
            "detail": {"row_count": len(buckets[COLLECTIVE_EXCLUDE])},
        },
        {
            "task_id": "s144:write_gate_contract_after_approval",
            "requirement_id": "relation_identity_write_gate",
            "status": "blocked_pending_approved_rows",
            "hard_blocking": True,
            "detail": {"approved_for_write_gate_count": 0, "write_gate_candidate_count": 0},
        },
    ]


def approved_disposition_requirements() -> list[str]:
    return [
        "disposition must be human-approved, not model-only or script-inferred",
        "disposition must be one of merge_to_canonical_after_source_backing, keep_separate_namesake_or_city_split, discard_invalid_or_ocr_damaged_profile, collective_or_lineup_not_dj, needs_more_evidence",
        "merge_to_canonical_after_source_backing requires source_ref_id_or_original_url, source_account_or_platform, published_at_or_event_date, evidence_title_or_quote, identity_match_notes, and field_preservation_notes",
        "collective_or_lineup_not_dj rows must be excluded from merge/write candidates",
        "needs_more_evidence rows must remain blocked until new source evidence changes their disposition",
    ]


def write_gate_contract() -> dict[str, Any]:
    return {
        "single_writer": {
            "required": True,
            "lock_scope": "db3_relation_identity_write_gate",
            "lock_file_pattern": "tools/stage7_rewrite/reports/atlas_relation_identity_write_gate_s144_*/db3_relation_identity.write.lock",
            "sqlite_busy_timeout_ms": 5000,
            "parallel_writers_allowed": False,
        },
        "backup_and_rollback": {
            "required": True,
            "backup_required_before_write": True,
            "backup_sha256_required": True,
            "rollback_restore_command_required": True,
            "retry_requires_restored_db_and_new_prewrite_snapshot": True,
        },
        "field_preservation": {
            "required": True,
            "policy": "non_empty_wins; never overwrite canonical non-empty values with empty/default/inferred values",
            "protected_tables": ["dj_profile", "subject", "dj_event", "dj_venue", "dj_collaborator", "source_ref"],
            "protected_fields": [
                "display_name",
                "aliases",
                "bio",
                "avatar",
                "external_music_links",
                "instagram_or_social_links",
                "mixtape",
                "event_id",
                "venue_id",
                "source_ref_id",
                "city",
                "starts_at",
                "relation_score",
                "same_event_count",
            ],
        },
        "postwrite_readback": {
            "required": True,
            "checks": [
                "all canonical dj_profile rows present",
                "old ids absent or quarantined in dj_profile and subject",
                "dj_event and dj_venue references redirected without row loss",
                "dj_collaborator redirects have no self loops unless explicitly quarantined",
                "source_ref_id counts and resolvability preserved",
                "row-count drift explained by duplicate-collapse contracts only",
                "no empty overwrite of protected fields",
            ],
        },
        "write_authorized_now": False,
    }


def build_report(
    *,
    recommendation_path: Path,
    evidence_path: Path,
    blocker_path: Path,
    candidate_limit: int,
) -> dict[str, Any]:
    recommendation = read_json(recommendation_path)
    evidence = read_json(evidence_path)
    blocker = read_json(blocker_path)
    rows = [row for row in as_list(recommendation.get("recommendation_rows")) if isinstance(row, dict)]
    buckets = split_rows(rows)
    candidate_slice = build_candidate_slice(buckets[MERGE_CANDIDATE], candidate_limit)
    recommendation_counts = Counter(str(row.get("recommendation") or "") for row in rows)
    approved_count = sum(1 for row in rows if row.get("approved_for_write_gate"))
    write_candidate_count = sum(1 for row in rows if row.get("write_gate_candidate"))
    decision = (
        "atlas_relation_identity_write_gate_closure_starter_blocked_report_only"
        if approved_count == 0 or write_candidate_count == 0
        else "atlas_relation_identity_write_gate_closure_starter_ready_report_only"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "current_story_id": CURRENT_STORY_ID,
        "decision": decision,
        "source_inputs": {
            "recommendation": rel_path(recommendation_path),
            "recommendation_decision": recommendation.get("decision"),
            "source_evidence": rel_path(evidence_path),
            "source_evidence_decision": evidence.get("decision"),
            "write_blocker": rel_path(blocker_path),
            "write_blocker_decision": blocker.get("decision"),
        },
        "input_counts": {
            "recommendation_row_count": len(rows),
            "source_evidence_enriched_row_count": evidence.get("enriched_row_count"),
            "source_evidence_rows_with_source_ref_candidates": evidence.get("rows_with_source_ref_candidates"),
            "source_evidence_rows_with_all_ids_source_ref_candidates": evidence.get(
                "rows_with_all_ids_source_ref_candidates"
            ),
            "blocker_relation_blocking_total_count": (blocker.get("relation_integrity") or {}).get(
                "blocking_total_count"
            ),
        },
        "recommendation_counts": dict(sorted(recommendation_counts.items())),
        "closure_counts": {
            "pending_human_approved_disposition": len(buckets[MERGE_CANDIDATE]),
            "evidence_acquisition_required": len(buckets[NEEDS_EVIDENCE]),
            "excluded_from_identity_merge": len(buckets[COLLECTIVE_EXCLUDE]),
            "candidate_slice_count": len(candidate_slice),
            "ready_for_validation_count": 0,
            "approved_for_write_gate_count": approved_count,
            "write_gate_candidate_count": write_candidate_count,
        },
        "approved_disposition_requirements": approved_disposition_requirements(),
        "write_gate_contract": write_gate_contract(),
        "candidate_slice": candidate_slice,
        "next_action_tasks": action_tasks(buckets, candidate_slice),
        "rules": [
            "S144 consumes full S141 recommendation/evidence packets, not older 24-row samples.",
            "Recommendations are routing hints only; they are not approvals.",
            "collective_or_lineup_not_dj rows are excluded from merge candidates.",
            "No row can enter a DB3 write gate without human-approved disposition, source-ref coverage, field preservation notes, lock, backup, rollback, and postwrite readback.",
            "No blocker is skipped; rows either remain blocked, are excluded without merge, or wait for an explicit future write gate.",
        ],
        "safety": {
            "report_only": True,
            "database_mutations": False,
            "identity_merge_executed": False,
            "write_gate_authorized": False,
            "db2_projection": False,
            "db3_identity_write": False,
            "deploy_upload_review": False,
            "provider_or_llm_call": False,
            "secret_read": False,
            "release_rebuild": False,
            "service_restart": False,
            "broad_disk_scan": False,
        },
    }


def render_markdown(report: dict[str, Any], paths: dict[str, str]) -> str:
    counts = report["closure_counts"]
    lines = [
        "# Atlas Relation Identity Write-Gate Closure Starter S144",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Recommendation input: `{report['source_inputs']['recommendation']}`",
        f"- Source evidence input: `{report['source_inputs']['source_evidence']}`",
        f"- Write blocker input: `{report['source_inputs']['write_blocker']}`",
        "",
        "## Counts",
        "",
        f"- Recommendation rows: `{report['input_counts']['recommendation_row_count']}`",
        f"- Pending human-approved disposition: `{counts['pending_human_approved_disposition']}`",
        f"- Evidence acquisition required: `{counts['evidence_acquisition_required']}`",
        f"- Excluded from identity merge: `{counts['excluded_from_identity_merge']}`",
        f"- Ready / approved / write-candidate: `{counts['ready_for_validation_count']}/{counts['approved_for_write_gate_count']}/{counts['write_gate_candidate_count']}`",
        f"- Candidate starter slice: `{counts['candidate_slice_count']}`",
        "",
        "## Output Files",
        "",
        f"- JSON: `{paths['json']}`",
        f"- Candidate slice: `{paths['candidate_slice']}`",
        f"- Pending human signoff rows: `{paths['pending_human_signoff']}`",
        f"- Evidence acquisition rows: `{paths['evidence_acquisition']}`",
        f"- Collective/lineup excluded rows: `{paths['collective_excluded']}`",
        f"- Tasks: `{paths['tasks']}`",
        "",
        "## Write-Gate Contract",
        "",
        "- Single DB3 writer is required with a lock file and SQLite busy timeout.",
        "- Backup, backup hash, rollback command, and restored-DB retry rule are required before any write.",
        "- Protected fields use non-empty-wins; empty/default values may not overwrite canonical non-empty values.",
        "- Postwrite readback must prove canonical rows, redirected references, source_ref integrity, no unexplained row-count drift, and no empty overwrite.",
        "",
        "## Boundary",
        "",
        "Report-only. No DB1/DB2/DB3 mutation, DB2 projection, DB3 identity write, deploy/upload/review, provider/model call, secret read, release rebuild, service restart, or broad disk scan occurred.",
        "",
    ]
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], out_dir: Path, scorecard: Path | None) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = report["candidate_slice"]
    pending = [row for row in rows_from_report(report, MERGE_CANDIDATE)]
    evidence = [row for row in rows_from_report(report, NEEDS_EVIDENCE)]
    excluded = [row for row in rows_from_report(report, COLLECTIVE_EXCLUDE)]
    paths = {
        "json": str(out_dir / "atlas_relation_identity_write_gate_closure_starter_s144.json"),
        "candidate_slice": str(out_dir / "write_gate_candidate_slice_s144.jsonl"),
        "pending_human_signoff": str(out_dir / "pending_human_signoff_rows_s144.jsonl"),
        "evidence_acquisition": str(out_dir / "evidence_acquisition_required_rows_s144.jsonl"),
        "collective_excluded": str(out_dir / "collective_lineup_excluded_rows_s144.jsonl"),
        "tasks": str(out_dir / "atlas_relation_identity_write_gate_closure_tasks_s144.jsonl"),
        "markdown": str(out_dir / "atlas_relation_identity_write_gate_closure_starter_s144.md"),
    }
    write_json(Path(paths["json"]), report)
    write_jsonl(Path(paths["candidate_slice"]), rows)
    write_jsonl(Path(paths["pending_human_signoff"]), pending)
    write_jsonl(Path(paths["evidence_acquisition"]), evidence)
    write_jsonl(Path(paths["collective_excluded"]), excluded)
    write_jsonl(Path(paths["tasks"]), report["next_action_tasks"])
    markdown = render_markdown(report, paths)
    Path(paths["markdown"]).write_text(markdown, encoding="utf-8")
    if scorecard is not None:
        scorecard.parent.mkdir(parents=True, exist_ok=True)
        scorecard.write_text(markdown, encoding="utf-8")
        paths["scorecard"] = str(scorecard)
    return paths


def rows_from_report(report: dict[str, Any], recommendation: str) -> list[dict[str, Any]]:
    path = Path(report["source_inputs"]["recommendation"])
    if not path.is_absolute():
        path = REPO_ROOT / path
    source = read_json(path)
    rows = [row for row in as_list(source.get("recommendation_rows")) if isinstance(row, dict)]
    buckets = split_rows(rows)
    return buckets[recommendation]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recommendation", type=Path, default=DEFAULT_RECOMMENDATION)
    parser.add_argument("--source-evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--write-blocker", type=Path, default=DEFAULT_BLOCKER)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--no-scorecard", action="store_true")
    parser.add_argument("--candidate-limit", type=int, default=25)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_report(
        recommendation_path=args.recommendation,
        evidence_path=args.source_evidence,
        blocker_path=args.write_blocker,
        candidate_limit=args.candidate_limit,
    )
    paths = write_outputs(report, args.out_dir, None if args.no_scorecard else args.scorecard)
    if args.json_only:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "decision": report["decision"],
                    "recommendation_row_count": report["input_counts"]["recommendation_row_count"],
                    "closure_counts": report["closure_counts"],
                    "json": paths["json"],
                    "tasks": paths["tasks"],
                    "scorecard": paths.get("scorecard"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
