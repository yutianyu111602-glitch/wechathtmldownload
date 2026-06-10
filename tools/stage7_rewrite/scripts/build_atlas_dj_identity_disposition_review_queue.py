#!/usr/bin/env python3
"""Build a report-only stable review queue for high-risk DB3 DJ dispositions."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TEMPLATE = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_high_risk_disposition_s76_20260531"
    / "atlas_dj_identity_high_risk_disposition_template.json"
)
DEFAULT_VALIDATION = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_high_risk_disposition_validation_s77_20260531"
    / "atlas_dj_identity_high_risk_disposition_validation.json"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_disposition_review_queue_s79_20260531"
)


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


def stable_review_item_id(row: dict[str, Any]) -> str:
    payload = {
        "group_id": row.get("group_id", ""),
        "canonical_dj_id": row.get("canonical_dj_id", ""),
        "all_dj_ids": sorted(str(item) for item in as_list(row.get("all_dj_ids")) if item),
        "merge_dj_ids": sorted(str(item) for item in as_list(row.get("merge_dj_ids")) if item),
    }
    digest = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"djidreview:{digest}"


def choose_next_action(row: dict[str, Any]) -> str:
    reasons = {str(reason) for reason in as_list(row.get("reason_codes")) if reason}
    default_disposition = str(row.get("default_disposition") or "")
    if default_disposition == "collective_or_lineup_not_dj" or "collective_or_lineup_label" in reasons:
        return "confirm_collective_or_lineup_non_dj_before_any_merge"
    if "short_identity_token" in reasons or "missing_city_key" in reasons:
        return "collect_source_refs_before_any_merge"
    if "multiple_merge_ids" in reasons:
        return "split_multi_merge_ids_before_any_write"
    return "complete_required_evidence_checks_before_any_write"


def build_queue_row(row: dict[str, Any], *, batch_size: int) -> dict[str, Any]:
    review_order = int(row.get("review_order") or 0)
    batch_number = ((max(review_order, 1) - 1) // max(batch_size, 1)) + 1
    return {
        "review_item_id": stable_review_item_id(row),
        "review_batch_id": f"s79-batch-{batch_number:03d}",
        "review_order": review_order,
        "group_id": row.get("group_id", ""),
        "risk_level": row.get("risk_level", ""),
        "priority_score": int(row.get("priority_score") or 0),
        "next_action": choose_next_action(row),
        "default_disposition": row.get("default_disposition", ""),
        "reason_codes": [str(reason) for reason in as_list(row.get("reason_codes")) if reason],
        "required_evidence_checks": [str(check) for check in as_list(row.get("required_evidence_checks")) if check],
        "canonical_dj_id": row.get("canonical_dj_id", ""),
        "merge_dj_ids": [str(item) for item in as_list(row.get("merge_dj_ids")) if item],
        "all_dj_ids": [str(item) for item in as_list(row.get("all_dj_ids")) if item],
        "display_names": [str(item) for item in as_list(row.get("display_names")) if item],
        "approved_for_write_gate": False,
        "write_gate_candidate": False,
        "safe_automerge": False,
        "database_write_allowed": False,
    }


def build_review_queue(
    template: dict[str, Any],
    validation: dict[str, Any],
    *,
    source_template: Path,
    source_validation: Path,
    batch_size: int = 10,
) -> dict[str, Any]:
    rows = [row for row in as_list(template.get("disposition_rows")) if isinstance(row, dict)]
    queue_rows = [build_queue_row(row, batch_size=batch_size) for row in rows]
    queue_rows.sort(key=lambda row: (row["review_order"], -row["priority_score"], row["review_item_id"]))
    review_item_ids = [row["review_item_id"] for row in queue_rows]
    disposition_counts = Counter(str(row.get("default_disposition") or "") for row in queue_rows)
    action_counts = Counter(str(row.get("next_action") or "") for row in queue_rows)
    batch_counts = Counter(str(row.get("review_batch_id") or "") for row in queue_rows)
    validation_blocked = int(validation.get("finding_count") or 0) > 0
    decision = (
        "atlas_dj_identity_disposition_review_queue_blocked_report_only"
        if validation_blocked
        else "atlas_dj_identity_disposition_review_queue_ready_report_only"
    )
    return {
        "schema_version": "atlas_dj_identity_disposition_review_queue.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "decision": decision,
        "source_template": rel(source_template),
        "source_template_decision": template.get("decision"),
        "source_validation": rel(source_validation),
        "source_validation_decision": validation.get("decision"),
        "source_validation_finding_count": int(validation.get("finding_count") or 0),
        "source_template_row_count": int(template.get("template_row_count") or len(rows)),
        "queue_row_count": len(queue_rows),
        "stable_review_item_ids_unique": len(review_item_ids) == len(set(review_item_ids)),
        "default_disposition_counts": dict(sorted(disposition_counts.items())),
        "next_action_counts": dict(sorted(action_counts.items())),
        "review_batch_counts": dict(sorted(batch_counts.items())),
        "batch_size": max(batch_size, 1),
        "approved_for_write_gate_count": 0,
        "write_gate_candidate_count": 0,
        "safe_automerge_allowed": False,
        "database_write_allowed": False,
        "review_queue_rows": queue_rows,
        "rules": [
            "review_item_id is deterministic from group_id and DJ ids, so review state can survive row reordering.",
            "This queue is for reviewer routing only; all write-gate flags remain false.",
            "Rows must pass S77 disposition validation before any later write-gate packet is considered.",
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
        "# Atlas DJ Identity Disposition Review Queue",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Source template: `{report['source_template']}`",
        f"- Source validation: `{report['source_validation']}`",
        f"- Queue rows: `{report['queue_row_count']}`",
        f"- Stable review ids unique: `{str(report['stable_review_item_ids_unique']).lower()}`",
        "",
        "## Review Queue Summary",
        "",
        "### Default Dispositions",
    ]
    for key, count in report["default_disposition_counts"].items():
        lines.append(f"- `{key}`: `{count}`")
    lines.extend(["", "### Next Actions"])
    for key, count in report["next_action_counts"].items():
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
    json_path = out_dir / "atlas_dj_identity_disposition_review_queue.json"
    rows_path = out_dir / "atlas_dj_identity_disposition_review_queue_rows.jsonl"
    md_path = out_dir / "atlas_dj_identity_disposition_review_queue.md"
    write_json(json_path, report)
    rows_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in report["review_queue_rows"]) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "rows": rows_path, "markdown": md_path}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--validation", type=Path, default=DEFAULT_VALIDATION)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or [])
    template = read_json(args.template)
    validation = read_json(args.validation)
    report = build_review_queue(
        template,
        validation,
        source_template=args.template,
        source_validation=args.validation,
        batch_size=args.batch_size,
    )
    paths = write_outputs(report, args.out_dir)
    summary = {
        "decision": report["decision"],
        "queue_row_count": report["queue_row_count"],
        "stable_review_item_ids_unique": report["stable_review_item_ids_unique"],
        "json": str(paths["json"]),
        "rows": str(paths["rows"]),
        "markdown": str(paths["markdown"]),
    }
    print(json.dumps(report if args.json_only else summary, ensure_ascii=False, indent=None if args.json_only else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
