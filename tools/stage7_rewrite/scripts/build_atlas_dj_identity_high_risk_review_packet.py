#!/usr/bin/env python3
"""Build a report-only high-risk DB3 DJ identity review packet.

Consumes the S73 identity review workbench and extracts only high-risk rows
for manual split/canonical review. This is evidence-only: no DB write, no
identity merge, no provider/LLM call, no deploy/upload.
"""
from __future__ import annotations

import argparse
import json
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
    / "atlas_dj_identity_high_risk_review_s75_20260531"
)


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_high_risk_row(row: dict[str, Any], *, order: int) -> dict[str, Any]:
    return {
        "review_order": order,
        "group_id": row.get("group_id", ""),
        "risk_level": row.get("risk_level", ""),
        "priority_score": int(row.get("priority_score") or 0),
        "reason_codes": row.get("reason_codes", []),
        "canonical_dj_id": row.get("canonical_dj_id", ""),
        "merge_dj_ids": row.get("merge_dj_ids", []),
        "all_dj_ids": row.get("all_dj_ids", []),
        "display_names": row.get("display_names", []),
        "identity_token": row.get("identity_token", ""),
        "city_key": row.get("city_key", ""),
        "total_event_rows": int(row.get("total_event_rows") or 0),
        "total_collaborator_edges": int(row.get("total_collaborator_edges") or 0),
        "total_venue_rows": int(row.get("total_venue_rows") or 0),
        "safe_automerge": False,
        "database_write_allowed": False,
        "review_required": True,
        "recommended_action": "manual_split_or_canonical_review_no_write",
        "review_questions": [
            "Is this a real individual DJ, a collective, a lineup label, or a generic role?",
            "If individual, which canonical dj_id should carry non-empty event, venue, collaborator, source, mixtape, social, bio, and avatar fields?",
            "Which merge ids must remain separate to avoid collapsing unrelated artists?",
        ],
    }


def build_packet(workbench: dict[str, Any], *, source_workbench: Path, limit: int | None) -> dict[str, Any]:
    rows = workbench.get("review_rows", []) if isinstance(workbench.get("review_rows"), list) else []
    high_rows = [row for row in rows if isinstance(row, dict) and row.get("risk_level") == "high"]
    high_rows.sort(key=lambda row: (-int(row.get("priority_score") or 0), str(row.get("group_id") or "")))
    selected = high_rows[:limit] if limit is not None and limit >= 0 else high_rows
    normalized_rows = [normalize_high_risk_row(row, order=index + 1) for index, row in enumerate(selected)]

    reason_counts = Counter(
        reason
        for row in normalized_rows
        for reason in row.get("reason_codes", [])
        if isinstance(reason, str) and reason
    )
    source_risk_counts = (
        workbench.get("risk_counts", {}) if isinstance(workbench.get("risk_counts"), dict) else {}
    )
    return {
        "schema_version": "atlas_dj_identity_high_risk_review_packet.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "decision": "atlas_dj_identity_high_risk_review_packet_ready_report_only",
        "source_workbench": rel(source_workbench),
        "source_decision": workbench.get("decision"),
        "source_review_row_count": int(workbench.get("review_row_count") or len(rows)),
        "source_merge_id_count": int(workbench.get("source_merge_id_count") or 0),
        "source_risk_counts": source_risk_counts,
        "high_risk_count": len(high_rows),
        "selected_count": len(normalized_rows),
        "limit": limit,
        "reason_counts": dict(sorted(reason_counts.items())),
        "safe_automerge_allowed": False,
        "database_write_allowed": False,
        "review_rows": normalized_rows,
        "rules": [
            "High-risk rows are manual-review only.",
            "Collective/lineup/generic labels must not be merged into individual DJs without explicit evidence.",
            "Short identity tokens must be checked for false-positive collisions before any write gate.",
            "Future writes must preserve non-empty event, venue, collaborator, source_ref, mixtape, social, bio, avatar, and evidence fields.",
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
        "# Atlas DJ Identity High Risk Review Packet",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Source workbench: `{report['source_workbench']}`",
        f"- Source review rows: `{report['source_review_row_count']}`",
        f"- Source merge ids: `{report['source_merge_id_count']}`",
        f"- High-risk rows: `{report['high_risk_count']}`",
        f"- Selected rows: `{report['selected_count']}`",
        "",
        "## Reason Counts",
    ]
    for key, value in report["reason_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## High Risk Review Rows"])
    for row in report["review_rows"]:
        lines.append(
            f"- `{row['review_order']}` `{row['group_id']}` canonical `{row['canonical_dj_id']}` "
            f"merge `{len(row['merge_dj_ids'])}` reasons `{','.join(row['reason_codes'])}`"
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
    json_path = out_dir / "atlas_dj_identity_high_risk_review_packet.json"
    jsonl_path = out_dir / "atlas_dj_identity_high_risk_review_rows.jsonl"
    markdown_path = out_dir / "atlas_dj_identity_high_risk_review_packet.md"
    write_json(json_path, report)
    write_jsonl(jsonl_path, report["review_rows"])
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "jsonl": jsonl_path, "markdown": markdown_path}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbench", type=Path, default=DEFAULT_WORKBENCH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    workbench = read_json(args.workbench)
    report = build_packet(workbench, source_workbench=args.workbench, limit=args.limit)
    paths = write_outputs(args.out_dir, report)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "source_review_row_count": report["source_review_row_count"],
                "high_risk_count": report["high_risk_count"],
                "selected_count": report["selected_count"],
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
