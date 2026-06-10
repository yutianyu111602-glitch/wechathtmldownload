#!/usr/bin/env python3
"""Build a no-write source-ref/disposition workbench for S115 starter rows.

This is a report-only bridge between S115's starter queue and any future DB3
identity write gate. It prepares review rows that require source refs,
identity-match notes, explicit disposition, and field-preservation notes before
any later validator can approve write-gate candidates.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_STARTER = (
    REPORTS_ROOT
    / "atlas_relation_identity_write_gate_starter_s115_20260601"
    / "atlas_relation_identity_write_gate_starter_packet.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_source_ref_disposition_workbench_s116_20260601"
DEFAULT_SCORECARD = (
    REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_SOURCE_REF_DISPOSITION_WORKBENCH_S116_20260601.md"
)
CURRENT_STORY_ID = "S116"

REQUIRED_REVIEW_FIELDS = [
    "source_ref_id_or_original_url",
    "source_account_or_platform",
    "published_at_or_event_date",
    "evidence_title_or_quote",
    "identity_match_notes",
    "field_preservation_notes",
    "disposition",
]

DISPOSITION_OPTIONS = [
    "needs_more_evidence",
    "keep_separate_namesake_or_city_split",
    "merge_to_canonical_after_source_backing",
    "discard_invalid_or_ocr_damaged_profile",
    "collective_or_lineup_not_dj",
]

FIELD_PRESERVATION_CHECKLIST = [
    "dj_event",
    "dj_venue",
    "dj_collaborator",
    "source_ref",
    "mixtape",
    "external_music_links",
    "instagram_or_social_links",
    "bio",
    "avatar",
    "aliases_and_display_names",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(read_text(path))


def rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def stable_id(*parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def selected_task_rows(starter: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in as_list(starter.get("next_action_tasks")):
        if not isinstance(task, dict) or task.get("hard_blocking") is True:
            continue
        detail = task.get("detail")
        if not isinstance(detail, dict):
            continue
        status = str(task.get("status") or "")
        if status not in {"needs_source_ref_collection", "needs_manual_identity_review"}:
            continue
        rows.append({"task": task, "detail": detail})
    rows.sort(
        key=lambda item: (
            str(item["detail"].get("lane") or ""),
            -int(item["detail"].get("priority_score") or 0),
            str(item["detail"].get("group_id") or ""),
        )
    )
    return rows


def build_review_row(item: dict[str, Any], order: int) -> dict[str, Any]:
    task = item["task"]
    detail = item["detail"]
    lane = str(detail.get("lane") or "")
    default_action = (
        "collect_source_refs_then_disposition"
        if lane == "high_risk_source_or_lineup_confirmation"
        else "manual_identity_disposition_with_field_preservation"
    )
    return {
        "workbench_row_id": "s116row:" + stable_id(task.get("task_id"), detail.get("group_id"), order),
        "source_task_id": task.get("task_id"),
        "source_starter_task_id": detail.get("task_id"),
        "review_order": order,
        "lane": lane,
        "risk_level": detail.get("risk_level"),
        "group_id": detail.get("group_id"),
        "city_key": detail.get("city_key"),
        "display_names": as_list(detail.get("display_names")),
        "canonical_dj_id": detail.get("canonical_dj_id"),
        "merge_dj_id_count": detail.get("merge_dj_id_count"),
        "all_dj_id_count": detail.get("all_dj_id_count"),
        "priority_score": detail.get("priority_score"),
        "relation_counts": {
            "event_rows": detail.get("total_event_rows"),
            "venue_rows": detail.get("total_venue_rows"),
            "collaborator_edges": detail.get("total_collaborator_edges"),
        },
        "reason_codes": as_list(detail.get("reason_codes")),
        "required_evidence_checks": as_list(detail.get("required_evidence_checks")),
        "required_review_fields": REQUIRED_REVIEW_FIELDS,
        "field_preservation_checklist": FIELD_PRESERVATION_CHECKLIST,
        "disposition_options": DISPOSITION_OPTIONS,
        "default_next_action": default_action,
        "draft": {
            "source_ref_id_or_original_url": "",
            "source_account_or_platform": "",
            "published_at_or_event_date": "",
            "evidence_title_or_quote": "",
            "identity_match_notes": "",
            "field_preservation_notes": "",
            "disposition": "needs_more_evidence",
            "reviewer_notes": "",
        },
        "ready_for_validation": False,
        "approved_for_write_gate": False,
        "write_gate_candidate": False,
        "safe_automerge": False,
        "database_write_allowed": False,
    }


def build_workbench(starter: dict[str, Any], *, starter_path: Path) -> dict[str, Any]:
    selected = selected_task_rows(starter)
    rows = [build_review_row(item, index + 1) for index, item in enumerate(selected)]
    lane_counts = Counter(str(row.get("lane") or "") for row in rows)
    risk_counts = Counter(str(row.get("risk_level") or "") for row in rows)
    required_blank_count = sum(
        1
        for row in rows
        for field in REQUIRED_REVIEW_FIELDS
        if not str(row["draft"].get(field) or "").strip()
        or (field == "disposition" and row["draft"].get(field) == "needs_more_evidence")
    )
    return {
        "schema_version": "atlas_relation_identity_source_ref_disposition_workbench.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "current_story_id": CURRENT_STORY_ID,
        "decision": "atlas_relation_identity_source_ref_disposition_workbench_pending_report_only",
        "source_starter_packet": rel_path(starter_path),
        "source_starter_decision": starter.get("decision"),
        "source_relation_blocking_total_count": starter.get("review_lanes", {}).get("relation_blocking_total_count"),
        "source_approved_for_write_gate_count": starter.get("review_lanes", {}).get("approved_for_write_gate_count"),
        "source_write_gate_candidate_count": starter.get("review_lanes", {}).get("write_gate_candidate_count"),
        "workbench_row_count": len(rows),
        "lane_counts": dict(sorted(lane_counts.items())),
        "risk_counts": dict(sorted(risk_counts.items())),
        "ready_for_validation_count": 0,
        "approved_for_write_gate_count": 0,
        "write_gate_candidate_count": 0,
        "required_blank_count": required_blank_count,
        "required_review_fields": REQUIRED_REVIEW_FIELDS,
        "field_preservation_checklist": FIELD_PRESERVATION_CHECKLIST,
        "disposition_options": DISPOSITION_OPTIONS,
        "review_rows": rows,
        "next_action_tasks": [
            {
                "task_id": "s116:fill_source_refs_for_high_risk_rows",
                "requirement_id": "relation_identity_write_gate",
                "status": "blocked_pending_source_ref_collection",
                "hard_blocking": True,
                "detail": {"row_count": lane_counts.get("high_risk_source_or_lineup_confirmation", 0)},
            },
            {
                "task_id": "s116:fill_disposition_for_non_high_rows",
                "requirement_id": "relation_identity_write_gate",
                "status": "blocked_pending_manual_disposition",
                "hard_blocking": True,
                "detail": {"row_count": lane_counts.get("non_high_priority_review", 0)},
            },
            {
                "task_id": "s116:preserve_non_empty_relation_and_profile_fields",
                "requirement_id": "empty_overwrite_and_relation_preservation",
                "status": "blocked_pending_field_preservation_notes",
                "hard_blocking": True,
                "detail": {"field_preservation_checklist": FIELD_PRESERVATION_CHECKLIST},
            },
        ],
        "rules": [
            "Rows are drafts until source refs, identity-match notes, disposition, and field-preservation notes are filled.",
            "No row can become a write-gate candidate from this workbench alone.",
            "Same normalized name is not sufficient evidence for merge.",
            "All non-empty event, venue, collaborator, source_ref, mixtape, social, bio, avatar, alias, and display-name fields must be preserved before any future write.",
        ],
        "safety": {
            "report_only": True,
            "database_mutations": False,
            "identity_merge_executed": False,
            "write_gate_authorized": False,
            "graph_vector_public_pointer_write": False,
            "coordinate_write": False,
            "openclaw_pipeline_run": False,
            "weekly_pipeline_run": False,
            "provider_or_geocode_call": False,
            "provider_or_llm_call": False,
            "devtools_launched": False,
            "deploy_upload_review": False,
            "secret_read": False,
            "release_rebuild": False,
            "service_restart": False,
            "broad_disk_scan": False,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Atlas Relation Identity Source Ref Disposition Workbench",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Current story: `{report['current_story_id']}`",
        f"- Source starter: `{report['source_starter_packet']}`",
        f"- Workbench rows: `{report['workbench_row_count']}`",
        f"- Ready for validation: `{report['ready_for_validation_count']}`",
        f"- Approved write-gate rows: `{report['approved_for_write_gate_count']}`",
        f"- Write-gate candidates: `{report['write_gate_candidate_count']}`",
        f"- Required blank/default fields: `{report['required_blank_count']}`",
        "",
        "## Lane Counts",
        "",
    ]
    for key, value in report["lane_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Review Rows", "", "| Order | Lane | Group | City | Names | Required Action |", "| --- | --- | --- | --- | --- | --- |"])
    for row in report["review_rows"]:
        names = ", ".join(str(name) for name in row["display_names"][:4]).replace("|", "\\|")
        lines.append(
            f"| `{row['review_order']}` | `{row['lane']}` | `{row['group_id']}` | {row.get('city_key') or ''} | {names} | `{row['default_next_action']}` |"
        )
    lines.extend(["", "## Field Preservation Checklist", ""])
    for field in report["field_preservation_checklist"]:
        lines.append(f"- `{field}`")
    lines.extend(["", "## Next Safe Actions", ""])
    for task in report["next_action_tasks"]:
        lines.append(f"- `{task['task_id']}`: `{task['status']}`; hard_blocking=`{task['hard_blocking']}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This workbench is report-only. It did not merge identities, mutate DB/graph/vector state, authorize a write gate, call providers or LLMs, deploy, upload, launch DevTools, read secrets, restart services, or scan broad disks.",
            "",
        ]
    )
    return "\n".join(lines)


def render_html(report: dict[str, Any]) -> str:
    rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(row['review_order']))}</td>"
        f"<td>{html.escape(str(row['lane']))}</td>"
        f"<td>{html.escape(str(row['group_id']))}</td>"
        f"<td>{html.escape(str(row.get('city_key') or ''))}</td>"
        f"<td>{html.escape(', '.join(str(name) for name in row['display_names'][:5]))}</td>"
        f"<td>{html.escape(str(row['default_next_action']))}</td>"
        "</tr>"
        for row in report["review_rows"]
    )
    return f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>Atlas Relation Identity S116 Workbench</title>
  <style>
    body {{ margin: 0; font-family: Segoe UI, Microsoft YaHei, Arial, sans-serif; background: #f5f7fa; color: #1f2933; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px 22px 48px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; }}
    .meta {{ color: #667085; margin-bottom: 18px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 18px 0; }}
    .card {{ background: #fff; border: 1px solid #d9dee7; border-radius: 8px; padding: 14px; }}
    .num {{ font-size: 24px; font-weight: 700; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d9dee7; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid #d9dee7; text-align: left; font-size: 13px; vertical-align: top; }}
    th {{ background: #eef2f6; }}
    code {{ background: #eef2f6; border: 1px solid #d9dee7; border-radius: 4px; padding: 1px 5px; }}
  </style>
</head>
<body>
  <main>
    <h1>Atlas Relation Identity S116 Workbench</h1>
    <div class=\"meta\">Decision: <code>{html.escape(report['decision'])}</code> · Source: <code>{html.escape(report['source_starter_packet'])}</code></div>
    <section class=\"grid\">
      <div class=\"card\"><div class=\"num\">{report['workbench_row_count']}</div><div>review rows</div></div>
      <div class=\"card\"><div class=\"num\">{report['ready_for_validation_count']}</div><div>ready rows</div></div>
      <div class=\"card\"><div class=\"num\">{report['approved_for_write_gate_count']}</div><div>approved rows</div></div>
      <div class=\"card\"><div class=\"num\">{report['write_gate_candidate_count']}</div><div>write candidates</div></div>
    </section>
    <table>
      <thead><tr><th>Order</th><th>Lane</th><th>Group</th><th>City</th><th>Names</th><th>Required Action</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </main>
</body>
</html>
"""


def write_reports(report: dict[str, Any], out_dir: Path, scorecard_path: Path | None) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "atlas_relation_identity_source_ref_disposition_workbench.json"
    md_path = out_dir / "atlas_relation_identity_source_ref_disposition_workbench.md"
    html_path = out_dir / "atlas_relation_identity_source_ref_disposition_workbench.html"
    rows_path = out_dir / "atlas_relation_identity_source_ref_disposition_rows.jsonl"
    markdown = render_markdown(report)
    write_json(json_path, report)
    write_jsonl(rows_path, report["review_rows"])
    md_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")
    paths = {
        "json": str(json_path),
        "markdown": str(md_path),
        "html": str(html_path),
        "rows": str(rows_path),
    }
    if scorecard_path is not None:
        scorecard_path.parent.mkdir(parents=True, exist_ok=True)
        scorecard_path.write_text(markdown, encoding="utf-8")
        paths["scorecard"] = str(scorecard_path)
    return paths


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--starter", type=Path, default=DEFAULT_STARTER)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--no-scorecard", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    starter = read_json(args.starter)
    report = build_workbench(starter, starter_path=args.starter)
    paths = write_reports(report, args.out_dir, None if args.no_scorecard else args.scorecard)
    if args.json_only:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "decision": report["decision"],
                    "current_story_id": report["current_story_id"],
                    "workbench_row_count": report["workbench_row_count"],
                    "ready_for_validation_count": report["ready_for_validation_count"],
                    "approved_for_write_gate_count": report["approved_for_write_gate_count"],
                    "write_gate_candidate_count": report["write_gate_candidate_count"],
                    "json": paths["json"],
                    "markdown": paths["markdown"],
                    "html": paths["html"],
                    "rows": paths["rows"],
                    "scorecard": paths.get("scorecard"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
