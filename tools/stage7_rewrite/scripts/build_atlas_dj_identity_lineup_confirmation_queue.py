#!/usr/bin/env python3
"""Build a report-only lineup/collective confirmation queue for high-risk DB3 DJ identities."""
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
DEFAULT_REVIEW_QUEUE = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_disposition_review_queue_s79_20260531"
    / "atlas_dj_identity_disposition_review_queue.json"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_lineup_confirmation_queue_s83_20260531"
)
SOURCE_REF_ACTION = "collect_source_refs_before_any_merge"
LINEUP_ACTION = "confirm_collective_or_lineup_non_dj_before_any_merge"
ALLOWED_CANDIDATE_CLASSIFICATIONS = [
    "lineup_or_event_billing_label",
    "collective_name",
    "generic_role_or_count_label",
    "individual_dj_identity",
    "needs_source_evidence",
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


def stable_lineup_confirmation_task_id(row: dict[str, Any]) -> str:
    payload = {
        "review_item_id": row.get("review_item_id", ""),
        "group_id": row.get("group_id", ""),
        "canonical_dj_id": row.get("canonical_dj_id", ""),
        "all_dj_ids": sorted(str(item) for item in as_list(row.get("all_dj_ids")) if item),
    }
    digest = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"djlineup:{digest}"


def build_lineup_confirmation_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "lineup_confirmation_task_id": stable_lineup_confirmation_task_id(row),
        "review_item_id": row.get("review_item_id", ""),
        "review_batch_id": row.get("review_batch_id", ""),
        "review_order": int(row.get("review_order") or 0),
        "group_id": row.get("group_id", ""),
        "risk_level": row.get("risk_level", ""),
        "priority_score": int(row.get("priority_score") or 0),
        "canonical_dj_id": row.get("canonical_dj_id", ""),
        "merge_dj_ids": [str(item) for item in as_list(row.get("merge_dj_ids")) if item],
        "all_dj_ids": [str(item) for item in as_list(row.get("all_dj_ids")) if item],
        "display_names": [str(item) for item in as_list(row.get("display_names")) if item],
        "reason_codes": [str(item) for item in as_list(row.get("reason_codes")) if item],
        "required_evidence_checks": [str(item) for item in as_list(row.get("required_evidence_checks")) if item],
        "allowed_candidate_classifications": ALLOWED_CANDIDATE_CLASSIFICATIONS,
        "candidate_classification": "",
        "classification_evidence_refs": [],
        "classification_notes": "",
        "field_preservation_notes": "",
        "ready_for_disposition_review": False,
        "approved_for_write_gate": False,
        "write_gate_candidate": False,
        "safe_automerge": False,
        "database_write_allowed": False,
    }


def build_lineup_confirmation_queue(review_queue: dict[str, Any], *, source_review_queue: Path) -> dict[str, Any]:
    rows = [row for row in as_list(review_queue.get("review_queue_rows")) if isinstance(row, dict)]
    lineup_rows = [
        build_lineup_confirmation_row(row) for row in rows if row.get("next_action") == LINEUP_ACTION
    ]
    lineup_rows.sort(key=lambda row: (row["review_order"], -row["priority_score"], row["lineup_confirmation_task_id"]))
    source_ref_rows = [row for row in rows if row.get("next_action") == SOURCE_REF_ACTION]
    reason_counts = Counter(reason for row in lineup_rows for reason in row["reason_codes"])
    batch_counts = Counter(str(row.get("review_batch_id") or "") for row in lineup_rows)
    task_ids = [row["lineup_confirmation_task_id"] for row in lineup_rows]
    return {
        "schema_version": "atlas_dj_identity_lineup_confirmation_queue.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "decision": "atlas_dj_identity_lineup_confirmation_queue_ready_report_only",
        "source_review_queue": rel(source_review_queue),
        "source_review_queue_decision": review_queue.get("decision"),
        "source_review_queue_row_count": int(review_queue.get("queue_row_count") or len(rows)),
        "lineup_confirmation_queue_row_count": len(lineup_rows),
        "source_ref_queue_row_count": len(source_ref_rows),
        "lineup_confirmation_task_ids_unique": len(task_ids) == len(set(task_ids)),
        "reason_counts": dict(sorted(reason_counts.items())),
        "review_batch_counts": dict(sorted(batch_counts.items())),
        "allowed_candidate_classifications": ALLOWED_CANDIDATE_CLASSIFICATIONS,
        "ready_for_disposition_review_count": 0,
        "approved_for_write_gate_count": 0,
        "write_gate_candidate_count": 0,
        "safe_automerge_allowed": False,
        "database_write_allowed": False,
        "lineup_confirmation_queue_rows": lineup_rows,
        "rules": [
            "This queue confirms whether lineup, collective, count, or role labels are non-DJ identities before any merge.",
            "Rows remain unapproved until classification evidence refs and field preservation notes are filled and revalidated.",
            "Blank classification fields must not overwrite existing DB1/DB2/DB3 non-empty fields.",
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
        "# Atlas DJ Identity Lineup Confirmation Queue",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Source review queue: `{report['source_review_queue']}`",
        f"- Lineup confirmation rows: `{report['lineup_confirmation_queue_row_count']}`",
        f"- Source-ref rows excluded: `{report['source_ref_queue_row_count']}`",
        f"- Lineup confirmation task ids unique: `{str(report['lineup_confirmation_task_ids_unique']).lower()}`",
        "",
        "## Lineup Confirmation Summary",
        "",
        "### Allowed Classifications",
    ]
    for item in report["allowed_candidate_classifications"]:
        lines.append(f"- `{item}`")
    lines.extend(["", "### Reason Counts"])
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
    json_path = out_dir / "atlas_dj_identity_lineup_confirmation_queue.json"
    rows_path = out_dir / "atlas_dj_identity_lineup_confirmation_queue_rows.jsonl"
    md_path = out_dir / "atlas_dj_identity_lineup_confirmation_queue.md"
    write_json(json_path, report)
    rows_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in report["lineup_confirmation_queue_rows"])
        + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "rows": rows_path, "markdown": md_path}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-queue", type=Path, default=DEFAULT_REVIEW_QUEUE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    review_queue = read_json(args.review_queue)
    report = build_lineup_confirmation_queue(review_queue, source_review_queue=args.review_queue)
    paths = write_outputs(report, args.out_dir)
    summary = {
        "decision": report["decision"],
        "lineup_confirmation_queue_row_count": report["lineup_confirmation_queue_row_count"],
        "source_ref_queue_row_count": report["source_ref_queue_row_count"],
        "lineup_confirmation_task_ids_unique": report["lineup_confirmation_task_ids_unique"],
        "json": str(paths["json"]),
        "rows": str(paths["rows"]),
        "markdown": str(paths["markdown"]),
    }
    print(json.dumps(report if args.json_only else summary, ensure_ascii=False, indent=None if args.json_only else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
