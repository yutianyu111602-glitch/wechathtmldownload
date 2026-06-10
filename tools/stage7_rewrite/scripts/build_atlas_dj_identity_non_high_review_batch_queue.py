#!/usr/bin/env python3
"""Build report-only review batches for non-high DB3 DJ identity rows."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKBENCH = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_review_workbench_s73_20260531"
    / "atlas_dj_identity_review_workbench.json"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_non_high_review_batch_queue_s87_20260531"
)
REQUIRED_EVIDENCE_CHECKS = [
    "source_ref_or_original_post_supports_identity",
    "non_empty_event_venue_collaborator_fields_preserved",
    "source_ref_mixtape_social_bio_avatar_fields_preserved_when_present",
    "same_name_is_not_sufficient_without_city_and_source_context",
]
REQUIRED_INPUTS = [
    "identity_match_evidence_refs",
    "canonical_choice_notes",
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


def stable_non_high_review_task_id(row: dict[str, Any]) -> str:
    payload = {
        "risk_level": row.get("risk_level", ""),
        "group_id": row.get("group_id", ""),
        "canonical_dj_id": row.get("canonical_dj_id", ""),
        "all_dj_ids": sorted(str(item) for item in as_list(row.get("all_dj_ids")) if item),
    }
    digest = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"djidentitynonhigh:{digest}"


def normalize_non_high_row(row: dict[str, Any], *, order: int, batch_size: int) -> dict[str, Any]:
    risk_level = str(row.get("risk_level") or "")
    batch_number = math.ceil(order / batch_size) if batch_size > 0 else 1
    return {
        "non_high_review_task_id": stable_non_high_review_task_id(row),
        "review_batch_id": f"s87-non-high-batch-{batch_number:03d}",
        "review_order": order,
        "risk_level": risk_level,
        "priority_score": as_int(row.get("priority_score")),
        "group_id": row.get("group_id", ""),
        "identity_token": row.get("identity_token", ""),
        "city_key": row.get("city_key", ""),
        "canonical_dj_id": row.get("canonical_dj_id", ""),
        "merge_dj_ids": [str(item) for item in as_list(row.get("merge_dj_ids")) if item],
        "all_dj_ids": [str(item) for item in as_list(row.get("all_dj_ids")) if item],
        "display_names": [str(item) for item in as_list(row.get("display_names")) if item],
        "normalized_names": [str(item) for item in as_list(row.get("normalized_names")) if item],
        "reason_codes": [str(item) for item in as_list(row.get("reason_codes")) if item],
        "total_event_rows": as_int(row.get("total_event_rows")),
        "total_collaborator_edges": as_int(row.get("total_collaborator_edges")),
        "total_venue_rows": as_int(row.get("total_venue_rows")),
        "next_required_action": "manual_identity_review_preserve_non_empty_fields",
        "required_inputs": REQUIRED_INPUTS,
        "required_evidence_checks": REQUIRED_EVIDENCE_CHECKS,
        "identity_match_evidence_refs": [],
        "canonical_choice_notes": "",
        "field_preservation_notes": "",
        "ready_for_disposition_review": False,
        "approved_for_write_gate": False,
        "write_gate_candidate": False,
        "safe_automerge": False,
        "database_write_allowed": False,
    }


def build_non_high_batch_queue(
    workbench: dict[str, Any],
    *,
    source_workbench: Path,
    batch_size: int,
) -> dict[str, Any]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    rows = [row for row in as_list(workbench.get("review_rows")) if isinstance(row, dict)]
    non_high_rows = [row for row in rows if row.get("risk_level") in {"medium", "low"}]
    risk_order = {"medium": 0, "low": 1}
    non_high_rows.sort(
        key=lambda row: (
            risk_order.get(str(row.get("risk_level")), 99),
            -as_int(row.get("priority_score")),
            str(row.get("group_id") or ""),
        )
    )
    normalized_rows = [
        normalize_non_high_row(row, order=index + 1, batch_size=batch_size)
        for index, row in enumerate(non_high_rows)
    ]
    task_ids = [row["non_high_review_task_id"] for row in normalized_rows]
    risk_counts = Counter(row["risk_level"] for row in normalized_rows)
    reason_counts = Counter(reason for row in normalized_rows for reason in row["reason_codes"])
    batch_counts = Counter(row["review_batch_id"] for row in normalized_rows)
    high_risk_excluded_count = sum(1 for row in rows if isinstance(row, dict) and row.get("risk_level") == "high")
    return {
        "schema_version": "atlas_dj_identity_non_high_review_batch_queue.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "decision": "atlas_dj_identity_non_high_review_batch_queue_ready_report_only",
        "source_workbench": rel(source_workbench),
        "source_decision": workbench.get("decision"),
        "source_review_row_count": as_int(workbench.get("review_row_count")) or len(rows),
        "source_merge_id_count": as_int(workbench.get("source_merge_id_count")),
        "high_risk_excluded_count": high_risk_excluded_count,
        "medium_risk_task_count": risk_counts.get("medium", 0),
        "low_risk_task_count": risk_counts.get("low", 0),
        "total_task_count": len(normalized_rows),
        "batch_size": batch_size,
        "batch_count": len(batch_counts),
        "risk_counts": dict(sorted(risk_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "review_batch_counts": dict(sorted(batch_counts.items())),
        "non_high_review_task_ids_unique": len(task_ids) == len(set(task_ids)),
        "ready_for_disposition_review_count": 0,
        "approved_for_write_gate_count": 0,
        "write_gate_candidate_count": 0,
        "safe_automerge_allowed": False,
        "database_write_allowed": False,
        "non_high_review_queue_rows": normalized_rows,
        "rules": [
            "Medium and low risk rows are still manual-review only; same normalized name is not enough for a write.",
            "Rows remain unapproved until source evidence, canonical-choice notes, and field-preservation notes are filled and revalidated.",
            "Blank review fields must not overwrite existing DB1/DB2/DB3 non-empty fields.",
            "Future write gates must preserve event, venue, collaborator, source_ref, mixtape, social, bio, avatar, and evidence fields.",
        ],
        "safety": {
            "report_only": True,
            "database_mutations": False,
            "identity_merge_executed": False,
            "source_mutations": False,
            "provider_or_llm_call": False,
            "secret_read": False,
            "deploy_upload_review": False,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Atlas DJ Identity Non-High Review Batch Queue",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Source workbench: `{report['source_workbench']}`",
        f"- Source review rows: `{report['source_review_row_count']}`",
        f"- High-risk rows excluded: `{report['high_risk_excluded_count']}`",
        f"- Medium-risk tasks: `{report['medium_risk_task_count']}`",
        f"- Low-risk tasks: `{report['low_risk_task_count']}`",
        f"- Total tasks: `{report['total_task_count']}`",
        f"- Batch size: `{report['batch_size']}`",
        f"- Batch count: `{report['batch_count']}`",
        "",
        "## Non-High Review Batch Summary",
        "",
        f"- Task ids unique: `{str(report['non_high_review_task_ids_unique']).lower()}`",
        f"- Database write allowed: `{str(report['database_write_allowed']).lower()}`",
        f"- Safe automerge allowed: `{str(report['safe_automerge_allowed']).lower()}`",
        "",
        "### Reason Counts",
    ]
    for key, count in report["reason_counts"].items():
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
    json_path = out_dir / "atlas_dj_identity_non_high_review_batch_queue.json"
    rows_path = out_dir / "atlas_dj_identity_non_high_review_batch_queue_rows.jsonl"
    md_path = out_dir / "atlas_dj_identity_non_high_review_batch_queue.md"
    write_json(json_path, report)
    rows_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in report["non_high_review_queue_rows"])
        + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "rows": rows_path, "markdown": md_path}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbench", type=Path, default=DEFAULT_WORKBENCH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = build_non_high_batch_queue(read_json(args.workbench), source_workbench=args.workbench, batch_size=args.batch_size)
    paths = write_outputs(report, args.out_dir)
    summary = {
        "decision": report["decision"],
        "source_review_row_count": report["source_review_row_count"],
        "high_risk_excluded_count": report["high_risk_excluded_count"],
        "medium_risk_task_count": report["medium_risk_task_count"],
        "low_risk_task_count": report["low_risk_task_count"],
        "total_task_count": report["total_task_count"],
        "batch_count": report["batch_count"],
        "json": str(paths["json"]),
        "rows": str(paths["rows"]),
        "markdown": str(paths["markdown"]),
    }
    print(json.dumps(report if args.json_only else summary, ensure_ascii=False, indent=None if args.json_only else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
