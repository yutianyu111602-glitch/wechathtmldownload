#!/usr/bin/env python3
"""Build one report-only next-action packet for pending high-risk DJ identity tasks."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_REF_QUEUE = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_source_ref_collection_queue_s81_20260531"
    / "atlas_dj_identity_source_ref_collection_queue.json"
)
DEFAULT_SOURCE_REF_VALIDATION = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_source_ref_collection_validation_s85_20260531"
    / "atlas_dj_identity_source_ref_collection_validation.json"
)
DEFAULT_LINEUP_QUEUE = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_lineup_confirmation_queue_s83_20260531"
    / "atlas_dj_identity_lineup_confirmation_queue.json"
)
DEFAULT_LINEUP_VALIDATION = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_lineup_confirmation_validation_s84_20260531"
    / "atlas_dj_identity_lineup_confirmation_validation.json"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_next_action_packet_s86_20260531"
)

SOURCE_REF_TASK_TYPE = "source_ref_collection"
LINEUP_TASK_TYPE = "lineup_confirmation"
SOURCE_REF_ACTION = "collect_source_refs_and_field_preservation_notes"
LINEUP_ACTION = "classify_lineup_or_collective_identity_with_evidence"
SOURCE_REF_REQUIRED_INPUTS = [
    "collected_source_refs",
    "identity_match_notes",
    "field_preservation_notes",
]
LINEUP_REQUIRED_INPUTS = [
    "candidate_classification",
    "classification_evidence_refs",
    "field_preservation_notes",
]


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def stable_next_action_task_id(task_type: str, row: dict[str, Any], source_task_id: str) -> str:
    payload = {
        "task_type": task_type,
        "source_task_id": source_task_id,
        "review_item_id": row.get("review_item_id", ""),
        "group_id": row.get("group_id", ""),
        "canonical_dj_id": row.get("canonical_dj_id", ""),
        "all_dj_ids": sorted(str(item) for item in as_list(row.get("all_dj_ids")) if item),
    }
    digest = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"djidentitynext:{digest}"


def common_row_fields(row: dict[str, Any], *, task_type: str, source_task_id: str) -> dict[str, Any]:
    return {
        "identity_next_action_task_id": stable_next_action_task_id(task_type, row, source_task_id),
        "task_type": task_type,
        "source_task_id": source_task_id,
        "review_item_id": row.get("review_item_id", ""),
        "review_batch_id": row.get("review_batch_id", ""),
        "review_order": as_int(row.get("review_order")),
        "group_id": row.get("group_id", ""),
        "risk_level": row.get("risk_level", ""),
        "priority_score": as_int(row.get("priority_score")),
        "canonical_dj_id": row.get("canonical_dj_id", ""),
        "merge_dj_ids": [str(item) for item in as_list(row.get("merge_dj_ids")) if item],
        "all_dj_ids": [str(item) for item in as_list(row.get("all_dj_ids")) if item],
        "display_names": [str(item) for item in as_list(row.get("display_names")) if item],
        "reason_codes": [str(item) for item in as_list(row.get("reason_codes")) if item],
        "required_evidence_checks": [str(item) for item in as_list(row.get("required_evidence_checks")) if item],
        "ready_for_disposition_review": row.get("ready_for_disposition_review") is True,
        "approved_for_write_gate": False,
        "write_gate_candidate": False,
        "safe_automerge": False,
        "database_write_allowed": False,
    }


def build_source_ref_next_action_row(row: dict[str, Any], *, validation_decision: str) -> dict[str, Any]:
    source_task_id = str(row.get("source_ref_task_id") or "")
    next_row = common_row_fields(row, task_type=SOURCE_REF_TASK_TYPE, source_task_id=source_task_id)
    next_row.update(
        {
            "next_required_action": SOURCE_REF_ACTION,
            "required_inputs": SOURCE_REF_REQUIRED_INPUTS,
            "validation_decision": validation_decision,
            "required_collection_fields": [
                str(item) for item in as_list(row.get("required_collection_fields")) if item
            ],
            "collected_source_refs": as_list(row.get("collected_source_refs")),
            "identity_match_notes": str(row.get("identity_match_notes") or ""),
            "field_preservation_notes": str(row.get("field_preservation_notes") or ""),
        }
    )
    return next_row


def build_lineup_next_action_row(row: dict[str, Any], *, validation_decision: str) -> dict[str, Any]:
    source_task_id = str(row.get("lineup_confirmation_task_id") or "")
    next_row = common_row_fields(row, task_type=LINEUP_TASK_TYPE, source_task_id=source_task_id)
    next_row.update(
        {
            "next_required_action": LINEUP_ACTION,
            "required_inputs": LINEUP_REQUIRED_INPUTS,
            "validation_decision": validation_decision,
            "allowed_candidate_classifications": [
                str(item) for item in as_list(row.get("allowed_candidate_classifications")) if item
            ],
            "candidate_classification": str(row.get("candidate_classification") or ""),
            "classification_evidence_refs": as_list(row.get("classification_evidence_refs")),
            "classification_notes": str(row.get("classification_notes") or ""),
            "field_preservation_notes": str(row.get("field_preservation_notes") or ""),
        }
    )
    return next_row


def build_next_action_packet(
    source_ref_queue: dict[str, Any],
    source_ref_validation: dict[str, Any],
    lineup_queue: dict[str, Any],
    lineup_validation: dict[str, Any],
    *,
    source_ref_queue_path: Path,
    source_ref_validation_path: Path,
    lineup_queue_path: Path,
    lineup_validation_path: Path,
) -> dict[str, Any]:
    source_validation_decision = str(source_ref_validation.get("decision") or "")
    lineup_validation_decision = str(lineup_validation.get("decision") or "")
    source_rows = [
        build_source_ref_next_action_row(row, validation_decision=source_validation_decision)
        for row in as_list(source_ref_queue.get("source_ref_queue_rows"))
        if isinstance(row, dict)
    ]
    lineup_rows = [
        build_lineup_next_action_row(row, validation_decision=lineup_validation_decision)
        for row in as_list(lineup_queue.get("lineup_confirmation_queue_rows"))
        if isinstance(row, dict)
    ]
    rows = source_rows + lineup_rows
    task_type_order = {SOURCE_REF_TASK_TYPE: 0, LINEUP_TASK_TYPE: 1}
    rows.sort(
        key=lambda row: (
            row["review_order"],
            task_type_order.get(str(row.get("task_type")), 99),
            -as_int(row.get("priority_score")),
            row["identity_next_action_task_id"],
        )
    )

    task_ids = [row["identity_next_action_task_id"] for row in rows]
    task_type_counts = Counter(row["task_type"] for row in rows)
    source_finding_count = as_int(source_ref_validation.get("finding_count"))
    lineup_finding_count = as_int(lineup_validation.get("finding_count"))
    ready_count = sum(1 for row in rows if row.get("ready_for_disposition_review") is True)
    return {
        "schema_version": "atlas_dj_identity_next_action_packet.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "decision": "atlas_dj_identity_next_action_packet_ready_report_only",
        "source_ref_queue": rel(source_ref_queue_path),
        "source_ref_validation": rel(source_ref_validation_path),
        "lineup_confirmation_queue": rel(lineup_queue_path),
        "lineup_confirmation_validation": rel(lineup_validation_path),
        "source_ref_queue_decision": source_ref_queue.get("decision"),
        "source_ref_validation_decision": source_ref_validation.get("decision"),
        "lineup_confirmation_queue_decision": lineup_queue.get("decision"),
        "lineup_confirmation_validation_decision": lineup_validation.get("decision"),
        "source_ref_task_count": len(source_rows),
        "lineup_confirmation_task_count": len(lineup_rows),
        "total_task_count": len(rows),
        "task_type_counts": dict(sorted(task_type_counts.items())),
        "identity_next_action_task_ids_unique": len(task_ids) == len(set(task_ids)),
        "source_ref_validation_finding_count": source_finding_count,
        "lineup_confirmation_validation_finding_count": lineup_finding_count,
        "all_validation_findings_zero": source_finding_count == 0 and lineup_finding_count == 0,
        "ready_for_disposition_review_count": ready_count,
        "approved_for_write_gate_count": 0,
        "write_gate_candidate_count": 0,
        "safe_automerge_allowed": False,
        "database_write_allowed": False,
        "next_action_rows": rows,
        "rules": [
            "This packet only consolidates pending identity tasks for human or later evidence review.",
            "Rows cannot approve identity merges, database writes, provider calls, deploys, uploads, or review submission.",
            "Blank action fields must not overwrite existing DB1/DB2/DB3 non-empty fields.",
            "Source-ref tasks need source refs, identity notes, and field preservation notes before later disposition review.",
            "Lineup tasks need classification evidence and field preservation notes before later disposition review.",
        ],
        "safety": {
            "report_only": True,
            "database_mutations": False,
            "identity_merge_executed": False,
            "source_mutations": False,
            "provider_or_llm_call": False,
            "deploy_upload_review": False,
            "secret_read": False,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Atlas DJ Identity Next Action Packet",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Source-ref tasks: `{report['source_ref_task_count']}`",
        f"- Lineup confirmation tasks: `{report['lineup_confirmation_task_count']}`",
        f"- Total tasks: `{report['total_task_count']}`",
        f"- Task ids unique: `{str(report['identity_next_action_task_ids_unique']).lower()}`",
        f"- Validation findings zero: `{str(report['all_validation_findings_zero']).lower()}`",
        f"- Ready rows: `{report['ready_for_disposition_review_count']}`",
        "",
        "## Identity Next Action Summary",
        "",
        f"- Source-ref validation: `{report['source_ref_validation_decision']}`",
        f"- Lineup validation: `{report['lineup_confirmation_validation_decision']}`",
        f"- Database write allowed: `{str(report['database_write_allowed']).lower()}`",
        f"- Safe automerge allowed: `{str(report['safe_automerge_allowed']).lower()}`",
        "",
        "### Task Type Counts",
    ]
    for key, count in report["task_type_counts"].items():
        lines.append(f"- `{key}`: `{count}`")
    lines.extend(
        [
            "",
            "## Safety Boundary",
            "",
            "- No DB writes.",
            "- No identity merge executed.",
            "- No source mutation.",
            "- No provider, LLM, deploy, upload, review, restart, or secret read.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "atlas_dj_identity_next_action_packet.json"
    rows_path = out_dir / "atlas_dj_identity_next_action_packet_rows.jsonl"
    md_path = out_dir / "atlas_dj_identity_next_action_packet.md"
    write_json(json_path, report)
    rows_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in report["next_action_rows"]) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "rows": rows_path, "markdown": md_path}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-ref-queue", type=Path, default=DEFAULT_SOURCE_REF_QUEUE)
    parser.add_argument("--source-ref-validation", type=Path, default=DEFAULT_SOURCE_REF_VALIDATION)
    parser.add_argument("--lineup-confirmation-queue", type=Path, default=DEFAULT_LINEUP_QUEUE)
    parser.add_argument("--lineup-confirmation-validation", type=Path, default=DEFAULT_LINEUP_VALIDATION)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = build_next_action_packet(
        read_json(args.source_ref_queue),
        read_json(args.source_ref_validation),
        read_json(args.lineup_confirmation_queue),
        read_json(args.lineup_confirmation_validation),
        source_ref_queue_path=args.source_ref_queue,
        source_ref_validation_path=args.source_ref_validation,
        lineup_queue_path=args.lineup_confirmation_queue,
        lineup_validation_path=args.lineup_confirmation_validation,
    )
    paths = write_outputs(report, args.out_dir)
    summary = {
        "decision": report["decision"],
        "source_ref_task_count": report["source_ref_task_count"],
        "lineup_confirmation_task_count": report["lineup_confirmation_task_count"],
        "total_task_count": report["total_task_count"],
        "all_validation_findings_zero": report["all_validation_findings_zero"],
        "json": str(paths["json"]),
        "rows": str(paths["rows"]),
        "markdown": str(paths["markdown"]),
    }
    print(json.dumps(report if args.json_only else summary, ensure_ascii=False, indent=None if args.json_only else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
