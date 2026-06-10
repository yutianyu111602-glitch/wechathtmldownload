#!/usr/bin/env python3
"""Build a report-only disposition template for high-risk DB3 DJ identities."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_HIGH_RISK_PACKET = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_high_risk_review_s75_20260531"
    / "atlas_dj_identity_high_risk_review_packet.json"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_high_risk_disposition_s76_20260531"
)
ALLOWED_DISPOSITIONS = [
    "keep_separate",
    "canonical_candidate",
    "collective_or_lineup_not_dj",
    "needs_source_evidence",
]


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def choose_default_disposition(reason_codes: list[str]) -> tuple[str, str]:
    reasons = set(reason_codes)
    if "collective_or_lineup_label" in reasons:
        return "collective_or_lineup_not_dj", "collective_or_lineup_label requires split/non-DJ review first"
    if "short_identity_token" in reasons or "missing_city_key" in reasons:
        return "needs_source_evidence", "short or city-missing identity token requires stronger source evidence"
    if "multiple_merge_ids" in reasons:
        return "keep_separate", "multiple merge ids should remain separate until reviewed"
    return "needs_source_evidence", "high-risk identity requires source evidence before any write gate"


def build_disposition_row(row: dict[str, Any]) -> dict[str, Any]:
    reason_codes = [str(reason) for reason in row.get("reason_codes", []) if reason]
    default_disposition, default_reason = choose_default_disposition(reason_codes)
    return {
        "review_order": row.get("review_order", 0),
        "group_id": row.get("group_id", ""),
        "risk_level": row.get("risk_level", ""),
        "priority_score": int(row.get("priority_score") or 0),
        "reason_codes": reason_codes,
        "canonical_dj_id": row.get("canonical_dj_id", ""),
        "merge_dj_ids": row.get("merge_dj_ids", []),
        "all_dj_ids": row.get("all_dj_ids", []),
        "display_names": row.get("display_names", []),
        "identity_token": row.get("identity_token", ""),
        "city_key": row.get("city_key", ""),
        "allowed_dispositions": ALLOWED_DISPOSITIONS,
        "default_disposition": default_disposition,
        "default_disposition_reason": default_reason,
        "reviewer_disposition": "",
        "reviewer_notes": "",
        "reviewer_evidence_refs": [],
        "required_evidence_checks": [
            "source_ref_or_original_post_supports_identity",
            "non_empty_event_venue_collaborator_fields_preserved",
            "mixtape_social_bio_avatar_fields_preserved_when_present",
            "not_a_collective_lineup_or_generic_role_before_merge",
        ],
        "approved_for_write_gate": False,
        "write_gate_candidate": False,
        "safe_automerge": False,
        "database_write_allowed": False,
    }


def build_template(packet: dict[str, Any], *, source_packet: Path) -> dict[str, Any]:
    rows = packet.get("review_rows", []) if isinstance(packet.get("review_rows"), list) else []
    disposition_rows = [build_disposition_row(row) for row in rows if isinstance(row, dict)]
    disposition_counts = Counter(row["default_disposition"] for row in disposition_rows)
    return {
        "schema_version": "atlas_dj_identity_high_risk_disposition_template.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "decision": "atlas_dj_identity_high_risk_disposition_template_ready_report_only",
        "source_high_risk_packet": rel(source_packet),
        "source_decision": packet.get("decision"),
        "source_review_row_count": int(packet.get("source_review_row_count") or 0),
        "source_merge_id_count": int(packet.get("source_merge_id_count") or 0),
        "source_high_risk_count": int(packet.get("high_risk_count") or len(rows)),
        "template_row_count": len(disposition_rows),
        "allowed_dispositions": ALLOWED_DISPOSITIONS,
        "default_disposition_counts": dict(sorted(disposition_counts.items())),
        "safe_automerge_allowed": False,
        "database_write_allowed": False,
        "disposition_rows": disposition_rows,
        "rules": [
            "Reviewer fields are intentionally blank until a human or later report-only agent fills them.",
            "approved_for_write_gate and write_gate_candidate remain false in this template.",
            "No row can progress to a write gate without source evidence and non-empty field preservation checks.",
            "Collective, lineup, and generic-role rows default away from DJ merge.",
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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Atlas DJ Identity High Risk Disposition Template",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Source high-risk packet: `{report['source_high_risk_packet']}`",
        f"- Source high-risk rows: `{report['source_high_risk_count']}`",
        f"- Template rows: `{report['template_row_count']}`",
        "",
        "## Disposition Counts",
    ]
    for key, value in report["default_disposition_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Template Rows"])
    for row in report["disposition_rows"]:
        lines.append(
            f"- `{row['review_order']}` `{row['group_id']}` default `{row['default_disposition']}` "
            f"reasons `{','.join(row['reason_codes'])}`"
        )
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


def write_outputs(out_dir: Path, report: dict[str, Any]) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "atlas_dj_identity_high_risk_disposition_template.json"
    jsonl_path = out_dir / "atlas_dj_identity_high_risk_disposition_rows.jsonl"
    markdown_path = out_dir / "atlas_dj_identity_high_risk_disposition_template.md"
    write_json(json_path, report)
    write_jsonl(jsonl_path, report["disposition_rows"])
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "jsonl": jsonl_path, "markdown": markdown_path}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--high-risk-packet", type=Path, default=DEFAULT_HIGH_RISK_PACKET)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packet = read_json(args.high_risk_packet)
    report = build_template(packet, source_packet=args.high_risk_packet)
    paths = write_outputs(args.out_dir, report)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "source_high_risk_count": report["source_high_risk_count"],
                "template_row_count": report["template_row_count"],
                "default_disposition_counts": report["default_disposition_counts"],
                "json": str(paths["json"]),
                "jsonl": str(paths["jsonl"]),
                "markdown": str(paths["markdown"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
