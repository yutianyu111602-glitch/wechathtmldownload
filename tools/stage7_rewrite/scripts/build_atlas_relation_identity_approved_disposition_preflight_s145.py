#!/usr/bin/env python3
"""Build a no-write approved-disposition preflight for relation identity rows.

S145 consumes the S144 starter slice and S141 evidence enrichment. It can mark a
row as an approved-disposition candidate for the next review/prewrite story, but
it never marks a row approved for DB3 write and never mutates DB1/DB2/DB3.
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
DEFAULT_S144_CLOSURE = (
    REPORTS_ROOT
    / "atlas_relation_identity_write_gate_closure_starter_s144_20260602"
    / "atlas_relation_identity_write_gate_closure_starter_s144.json"
)
DEFAULT_S144_SLICE = (
    REPORTS_ROOT
    / "atlas_relation_identity_write_gate_closure_starter_s144_20260602"
    / "write_gate_candidate_slice_s144.jsonl"
)
DEFAULT_S141_EVIDENCE = (
    REPORTS_ROOT
    / "atlas_relation_identity_source_evidence_enrichment_s141_full_20260602"
    / "atlas_relation_identity_source_evidence_enrichment.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_approved_disposition_preflight_s145_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_APPROVED_DISPOSITION_PREFLIGHT_S145_20260602.md"
CURRENT_STORY_ID = "S145"
SCHEMA_VERSION = "atlas_relation_identity_approved_disposition_preflight.v1"

APPROVED_DISPOSITION_CANDIDATE = "approved_disposition_candidate"
EVIDENCE_GAP = "blocked_evidence_gap"
COLLECTIVE_EXCLUDED = "blocked_collective_or_lineup_not_dj"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


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


def compact(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def is_collective_or_lineup(row: dict[str, Any]) -> bool:
    text_parts = [
        str(row.get("recommendation") or ""),
        str(row.get("suggested_disposition") or ""),
        str(row.get("closure_status") or ""),
        " ".join(str(flag) for flag in as_list(row.get("review_flags"))),
    ]
    text = " ".join(text_parts).lower()
    return any(token in text for token in ["collective_or_lineup_not_dj", "collective", "lineup_not_dj"])


def write_contract_from_closure(closure: dict[str, Any]) -> dict[str, Any]:
    contract = closure.get("write_gate_contract")
    if isinstance(contract, dict):
        return contract
    return {
        "single_writer": {"required": True},
        "backup_and_rollback": {"required": True},
        "field_preservation": {"required": True, "policy": "non_empty_wins"},
        "postwrite_readback": {"required": True},
        "write_authorized_now": False,
    }


def contract_ready_no_write(contract: dict[str, Any]) -> tuple[bool, list[str]]:
    gaps: list[str] = []
    if not ((contract.get("single_writer") or {}).get("required")):
        gaps.append("single_writer_lock_contract_missing")
    if not ((contract.get("backup_and_rollback") or {}).get("required")):
        gaps.append("backup_rollback_contract_missing")
    if not ((contract.get("field_preservation") or {}).get("required")):
        gaps.append("field_preservation_contract_missing")
    if not ((contract.get("postwrite_readback") or {}).get("required")):
        gaps.append("postwrite_readback_contract_missing")
    if contract.get("write_authorized_now") is not False:
        gaps.append("write_authorization_boundary_not_false")
    return (not gaps, gaps)


def source_ref_samples_for_dj(evidence: dict[str, Any], dj_id: str, limit: int = 2) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for item in as_list(evidence.get("source_ref_candidates")):
        if not isinstance(item, dict) or str(item.get("evidence_dj_id") or "") != dj_id:
            continue
        samples.append(
            {
                "source_ref_id": item.get("source_ref_id", ""),
                "source_hash": item.get("source_hash", ""),
                "source_account": compact(item.get("source_account"), 120),
                "source_title": compact(item.get("source_title"), 160),
                "post_date": item.get("post_date", ""),
                "source_kind": item.get("source_kind", ""),
                "event_id": item.get("evidence_event_id", ""),
                "event_title": compact(item.get("evidence_event_title"), 160),
                "event_date": item.get("evidence_starts_at", ""),
                "venue_name": compact(item.get("evidence_venue_name"), 120),
                "city": item.get("evidence_city", ""),
            }
        )
        if len(samples) >= limit:
            return samples

    events = (evidence.get("event_evidence_by_dj") or {}).get(dj_id) or []
    for event in events:
        if not isinstance(event, dict) or not str(event.get("source_ref_id") or "").strip():
            continue
        samples.append(
            {
                "source_ref_id": event.get("source_ref_id", ""),
                "source_hash": event.get("source_hash", ""),
                "source_account": compact(event.get("source_account"), 120),
                "source_title": compact(event.get("source_title"), 160),
                "post_date": event.get("post_date", ""),
                "source_kind": event.get("source_kind", ""),
                "event_id": event.get("event_id", ""),
                "event_title": compact(event.get("event_title"), 160),
                "event_date": event.get("starts_at", ""),
                "venue_name": compact(event.get("venue_name"), 120),
                "city": event.get("city", ""),
            }
        )
        if len(samples) >= limit:
            break
    return samples


def sample_events(evidence: dict[str, Any], dj_id: str, limit: int = 2) -> list[dict[str, Any]]:
    rows = []
    for event in as_list((evidence.get("event_evidence_by_dj") or {}).get(dj_id))[:limit]:
        if not isinstance(event, dict):
            continue
        rows.append(
            {
                "event_id": event.get("event_id", ""),
                "event_title": compact(event.get("event_title"), 160),
                "starts_at": event.get("starts_at", ""),
                "venue_id": event.get("venue_id", ""),
                "venue_name": compact(event.get("venue_name"), 120),
                "city": event.get("city", ""),
                "source_ref_id": event.get("source_ref_id", ""),
                "source_title": compact(event.get("source_title"), 160),
                "confidence": event.get("confidence", 0),
            }
        )
    return rows


def sample_venues(evidence: dict[str, Any], dj_id: str, limit: int = 2) -> list[dict[str, Any]]:
    rows = []
    for venue in as_list((evidence.get("venue_evidence_by_dj") or {}).get(dj_id))[:limit]:
        if not isinstance(venue, dict):
            continue
        rows.append(
            {
                "venue_id": venue.get("venue_id", ""),
                "venue_name": compact(venue.get("venue_name"), 120),
                "city": venue.get("city", ""),
                "event_count": int_value(venue.get("event_count")),
                "first_seen_at": venue.get("first_seen_at", ""),
                "last_seen_at": venue.get("last_seen_at", ""),
            }
        )
    return rows


def sample_collaborators(evidence: dict[str, Any], dj_id: str, limit: int = 2) -> list[dict[str, Any]]:
    rows = []
    for collab in as_list((evidence.get("collaborator_evidence_by_dj") or {}).get(dj_id))[:limit]:
        if not isinstance(collab, dict):
            continue
        rows.append(
            {
                "src_dj_id": collab.get("src_dj_id", ""),
                "dst_dj_id": collab.get("dst_dj_id", ""),
                "src_display_name": compact(collab.get("src_display_name"), 100),
                "dst_display_name": compact(collab.get("dst_display_name"), 100),
                "same_event_count": int_value(collab.get("same_event_count")),
                "relation_label_zh": collab.get("relation_label_zh", ""),
                "relation_score": collab.get("relation_score", 0),
            }
        )
    return rows


def profiles_by_id(evidence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for profile in as_list(evidence.get("profile_evidence")):
        if isinstance(profile, dict) and str(profile.get("dj_id") or ""):
            out[str(profile.get("dj_id"))] = {
                "dj_id": profile.get("dj_id", ""),
                "display_name": compact(profile.get("display_name"), 100),
                "normalized_name": compact(profile.get("normalized_name"), 100),
                "aliases_json": compact(profile.get("aliases_json"), 220),
                "city_primary": profile.get("city_primary", ""),
                "event_count": int_value(profile.get("event_count")),
                "venue_count": int_value(profile.get("venue_count")),
                "collaborator_count": int_value(profile.get("collaborator_count")),
                "has_bio": bool(profile.get("has_bio")),
                "bio_source": compact(profile.get("bio_source"), 100),
                "has_avatar": bool(profile.get("has_avatar")),
                "first_seen_at": profile.get("first_seen_at", ""),
                "last_seen_at": profile.get("last_seen_at", ""),
            }
    return out


def build_per_identity_evidence(row: dict[str, Any], evidence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    profiles = profiles_by_id(evidence)
    per_id: dict[str, dict[str, Any]] = {}
    for dj_id in [str(value) for value in as_list(row.get("all_dj_ids")) if str(value)]:
        per_id[dj_id] = {
            "profile": profiles.get(dj_id, {}),
            "source_ref_samples": source_ref_samples_for_dj(evidence, dj_id),
            "event_samples": sample_events(evidence, dj_id),
            "venue_samples": sample_venues(evidence, dj_id),
            "collaborator_samples": sample_collaborators(evidence, dj_id),
        }
    return per_id


def field_preservation_notes(row: dict[str, Any], per_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    canonical_id = str(row.get("canonical_dj_id") or "")
    merge_ids = [str(value) for value in as_list(row.get("merge_dj_ids")) if str(value)]
    protected = {}
    for dj_id in [canonical_id] + merge_ids:
        if not dj_id:
            continue
        profile = per_id.get(dj_id, {}).get("profile") or {}
        protected[dj_id] = {
            "display_name": profile.get("display_name", ""),
            "normalized_name": profile.get("normalized_name", ""),
            "aliases_json": profile.get("aliases_json", ""),
            "city_primary": profile.get("city_primary", ""),
            "has_bio": bool(profile.get("has_bio")),
            "bio_source": profile.get("bio_source", ""),
            "has_avatar": bool(profile.get("has_avatar")),
            "event_count": int_value(profile.get("event_count")),
            "venue_count": int_value(profile.get("venue_count")),
            "collaborator_count": int_value(profile.get("collaborator_count")),
        }
    return {
        "policy": "non_empty_wins; no canonical non-empty profile/relation/source field may be overwritten by empty/default values",
        "canonical_dj_id": canonical_id,
        "merge_dj_ids": merge_ids,
        "protected_profile_state": protected,
        "relation_tables": ["dj_event", "dj_venue", "dj_collaborator", "source_ref"],
        "postwrite_required": [
            "canonical profile preserved",
            "source_ref resolvability preserved",
            "no event/venue/collaborator row loss",
            "no unexplained row-count drift",
            "no empty overwrite",
        ],
    }


def evaluate_row(row: dict[str, Any], evidence: dict[str, Any], contract_ok: bool, contract_gaps: list[str]) -> dict[str, Any]:
    all_ids = [str(value) for value in as_list(row.get("all_dj_ids")) if str(value)]
    per_id = build_per_identity_evidence(row, evidence)
    gaps: list[str] = []
    if not evidence:
        gaps.append("s141_evidence_row_missing")
    if is_collective_or_lineup(row):
        gaps.append("collective_or_lineup_not_dj_excluded")
    ids_with_source = {str(value) for value in as_list(evidence.get("ids_with_source_ref"))}
    missing_source_ids = [dj_id for dj_id in all_ids if dj_id not in ids_with_source]
    if missing_source_ids:
        gaps.append("source_ref_coverage_incomplete:" + ",".join(missing_source_ids))
    for dj_id in all_ids:
        channels = per_id.get(dj_id) or {}
        if not channels.get("profile"):
            gaps.append(f"profile_missing:{dj_id}")
        if not channels.get("source_ref_samples"):
            gaps.append(f"source_ref_sample_missing:{dj_id}")
        if not channels.get("event_samples"):
            gaps.append(f"event_evidence_missing:{dj_id}")
        if not channels.get("venue_samples"):
            gaps.append(f"venue_evidence_missing:{dj_id}")
        if not channels.get("collaborator_samples"):
            gaps.append(f"collaborator_evidence_missing:{dj_id}")
    if not contract_ok:
        gaps.extend(contract_gaps)
    field_notes = field_preservation_notes(row, per_id)
    if not field_notes.get("protected_profile_state"):
        gaps.append("field_preservation_profile_state_missing")
    status = COLLECTIVE_EXCLUDED if "collective_or_lineup_not_dj_excluded" in gaps else EVIDENCE_GAP
    if not gaps:
        status = APPROVED_DISPOSITION_CANDIDATE
    identity_match_notes = {
        "group_id": row.get("group_id", ""),
        "display_names": as_list(row.get("display_names")),
        "canonical_dj_id": row.get("canonical_dj_id", ""),
        "merge_dj_ids": as_list(row.get("merge_dj_ids")),
        "match_basis": [
            "same normalized/compact display-name group from S141/S144",
            "all IDs have source-ref coverage in S141 evidence",
            "all IDs have event, venue, and collaborator evidence in this preflight" if not gaps else "evidence gaps listed in gap_codes",
        ],
        "approval_status": "preflight_candidate_not_write_approval" if status == APPROVED_DISPOSITION_CANDIDATE else "blocked_before_approval",
    }
    return {
        "workbench_row_id": row.get("workbench_row_id", ""),
        "recommendation_row_id": row.get("recommendation_row_id", ""),
        "review_order": row.get("review_order"),
        "group_id": row.get("group_id", ""),
        "city_key": row.get("city_key", ""),
        "display_names": as_list(row.get("display_names")),
        "canonical_dj_id": row.get("canonical_dj_id", ""),
        "merge_dj_ids": as_list(row.get("merge_dj_ids")),
        "all_dj_ids": all_ids,
        "preflight_status": status,
        "gap_codes": gaps,
        "source_ref_coverage_complete": not any(code.startswith("source_ref_coverage_incomplete") for code in gaps),
        "per_identity_evidence": per_id,
        "identity_match_notes": identity_match_notes,
        "field_preservation_notes": field_notes,
        "suggested_disposition": row.get("suggested_disposition", "merge_to_canonical_after_source_backing"),
        "operator_approval_required": True,
        "ready_for_validation": False,
        "approved_for_write_gate": False,
        "write_gate_candidate": False,
        "database_write_allowed": False,
    }


def action_tasks(report_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    status_counts = Counter(row["preflight_status"] for row in report_rows)
    candidate_count = status_counts.get(APPROVED_DISPOSITION_CANDIDATE, 0)
    gap_count = status_counts.get(EVIDENCE_GAP, 0) + status_counts.get(COLLECTIVE_EXCLUDED, 0)
    return [
        {
            "task_id": "s145:operator_review_approved_disposition_candidates",
            "requirement_id": "relation_identity_write_gate",
            "status": "blocked_pending_operator_approval_and_s146_prewrite_gate",
            "hard_blocking": True,
            "detail": {"approved_disposition_candidate_count": candidate_count},
        },
        {
            "task_id": "s145:evidence_gaps_for_non_candidates",
            "requirement_id": "relation_identity_write_gate",
            "status": "blocked_pending_source_evidence_or_disposition_repair",
            "hard_blocking": gap_count > 0,
            "detail": {"gap_row_count": gap_count},
        },
        {
            "task_id": "s145:db3_write_gate_still_not_authorized",
            "requirement_id": "relation_identity_write_gate",
            "status": "blocked_no_db3_write_until_later_single_writer_prewrite_gate",
            "hard_blocking": True,
            "detail": {
                "ready_for_validation_count": 0,
                "approved_for_write_gate_count": 0,
                "write_gate_candidate_count": 0,
            },
        },
    ]


def build_report(
    *,
    candidate_slice_path: Path,
    source_evidence_path: Path,
    closure_starter_path: Path,
) -> dict[str, Any]:
    candidate_slice = read_jsonl(candidate_slice_path)
    evidence = read_json(source_evidence_path)
    closure = read_json(closure_starter_path)
    evidence_by_row = {
        str(row.get("workbench_row_id")): row
        for row in as_list(evidence.get("enriched_rows"))
        if isinstance(row, dict) and str(row.get("workbench_row_id") or "")
    }
    contract = write_contract_from_closure(closure)
    contract_ok, contract_gaps = contract_ready_no_write(contract)
    rows = [
        evaluate_row(row, evidence_by_row.get(str(row.get("workbench_row_id"))) or {}, contract_ok, contract_gaps)
        for row in candidate_slice
    ]
    status_counts = Counter(row["preflight_status"] for row in rows)
    candidate_rows = [row for row in rows if row["preflight_status"] == APPROVED_DISPOSITION_CANDIDATE]
    gap_rows = [row for row in rows if row["preflight_status"] != APPROVED_DISPOSITION_CANDIDATE]
    decision = (
        "atlas_relation_identity_approved_disposition_preflight_candidates_ready_report_only"
        if candidate_rows
        else "atlas_relation_identity_approved_disposition_preflight_blocked_report_only"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "current_story_id": CURRENT_STORY_ID,
        "decision": decision,
        "source_inputs": {
            "s144_closure_starter": rel_path(closure_starter_path),
            "s144_closure_decision": closure.get("decision"),
            "s144_candidate_slice": rel_path(candidate_slice_path),
            "s141_source_evidence": rel_path(source_evidence_path),
            "s141_source_evidence_decision": evidence.get("decision"),
        },
        "input_counts": {
            "candidate_slice_count": len(candidate_slice),
            "source_evidence_enriched_row_count": evidence.get("enriched_row_count"),
            "joined_evidence_row_count": sum(1 for row in candidate_slice if str(row.get("workbench_row_id")) in evidence_by_row),
        },
        "preflight_counts": {
            "approved_disposition_candidate_count": len(candidate_rows),
            "gap_row_count": len(gap_rows),
            "ready_for_validation_count": 0,
            "approved_for_write_gate_count": 0,
            "write_gate_candidate_count": 0,
        },
        "preflight_status_counts": dict(sorted(status_counts.items())),
        "criteria": [
            "same S144 starter row and S141 evidence row joined by workbench_row_id",
            "not collective_or_lineup_not_dj",
            "all all_dj_ids covered by S141 source_ref evidence",
            "each canonical/merge id has concrete source_ref, event, venue, and collaborator evidence samples",
            "profile state exists for each id so field preservation can be computed",
            "S144 single-writer, backup/rollback, field-preservation, and postwrite-readback contracts are present",
            "preflight candidates are still not ready_for_validation, not approved_for_write_gate, and not DB write candidates",
        ],
        "write_gate_contract": contract,
        "write_gate_contract_ready_no_write": contract_ok,
        "approved_disposition_candidate_rows": candidate_rows,
        "gap_rows": gap_rows,
        "evidence_rows": rows,
        "next_action_tasks": action_tasks(rows),
        "rules": [
            "S145 consumes the S144 first candidate slice and S141 full evidence; it does not use the older 24-row sample.",
            "approved_disposition_candidate means enough evidence for operator/prewrite review, not approval to write DB3.",
            "No row becomes ready_for_validation, approved_for_write_gate, or write_gate_candidate in S145.",
            "Rows with missing evidence remain blocked with explicit gap_codes; blockers are not skipped.",
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
    counts = report["preflight_counts"]
    lines = [
        "# Atlas Relation Identity Approved-Disposition Preflight S145",
        "",
        f"- Decision: `{report['decision']}`",
        f"- S144 slice: `{report['source_inputs']['s144_candidate_slice']}`",
        f"- S141 evidence: `{report['source_inputs']['s141_source_evidence']}`",
        f"- Input / joined rows: `{report['input_counts']['candidate_slice_count']}/{report['input_counts']['joined_evidence_row_count']}`",
        f"- Approved-disposition candidates: `{counts['approved_disposition_candidate_count']}`",
        f"- Gap rows: `{counts['gap_row_count']}`",
        f"- Ready / approved / write-candidate: `{counts['ready_for_validation_count']}/{counts['approved_for_write_gate_count']}/{counts['write_gate_candidate_count']}`",
        "",
        "## Output Files",
        "",
        f"- JSON: `{paths['json']}`",
        f"- Evidence rows: `{paths['evidence_rows']}`",
        f"- Approved-disposition candidates: `{paths['approved_candidates']}`",
        f"- Gap rows: `{paths['gap_rows']}`",
        f"- Tasks: `{paths['tasks']}`",
        "",
        "## Interpretation",
        "",
        "- `approved_disposition_candidate` means evidence is complete enough for the next operator/prewrite review.",
        "- It does not mean `approved_for_write_gate`; S145 keeps DB3 write authorization at zero.",
        "- Gap rows stay blocked with explicit `gap_codes` instead of being skipped.",
        "",
        "## Boundary",
        "",
        "Report-only. No DB1/DB2/DB3 mutation, DB2 projection, DB3 identity write, deploy/upload/review, provider/model call, secret read, release rebuild, service restart, or broad disk scan occurred.",
        "",
    ]
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], out_dir: Path, scorecard: Path | None) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": str(out_dir / "atlas_relation_identity_approved_disposition_preflight_s145.json"),
        "evidence_rows": str(out_dir / "approved_disposition_preflight_evidence_rows_s145.jsonl"),
        "approved_candidates": str(out_dir / "approved_disposition_candidate_rows_s145.jsonl"),
        "gap_rows": str(out_dir / "approved_disposition_gap_rows_s145.jsonl"),
        "tasks": str(out_dir / "atlas_relation_identity_approved_disposition_preflight_tasks_s145.jsonl"),
        "markdown": str(out_dir / "atlas_relation_identity_approved_disposition_preflight_s145.md"),
    }
    write_json(Path(paths["json"]), report)
    write_jsonl(Path(paths["evidence_rows"]), report["evidence_rows"])
    write_jsonl(Path(paths["approved_candidates"]), report["approved_disposition_candidate_rows"])
    write_jsonl(Path(paths["gap_rows"]), report["gap_rows"])
    write_jsonl(Path(paths["tasks"]), report["next_action_tasks"])
    markdown = render_markdown(report, paths)
    Path(paths["markdown"]).write_text(markdown, encoding="utf-8")
    if scorecard is not None:
        scorecard.parent.mkdir(parents=True, exist_ok=True)
        scorecard.write_text(markdown, encoding="utf-8")
        paths["scorecard"] = str(scorecard)
    return paths


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-slice", type=Path, default=DEFAULT_S144_SLICE)
    parser.add_argument("--source-evidence", type=Path, default=DEFAULT_S141_EVIDENCE)
    parser.add_argument("--closure-starter", type=Path, default=DEFAULT_S144_CLOSURE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--no-scorecard", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_report(
        candidate_slice_path=args.candidate_slice,
        source_evidence_path=args.source_evidence,
        closure_starter_path=args.closure_starter,
    )
    paths = write_outputs(report, args.out_dir, None if args.no_scorecard else args.scorecard)
    if args.json_only:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "decision": report["decision"],
                    "input_counts": report["input_counts"],
                    "preflight_counts": report["preflight_counts"],
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
