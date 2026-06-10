#!/usr/bin/env python3
"""Build a report-only disposition recommendation packet for S139 evidence rows."""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_SOURCE_EVIDENCE = (
    REPORTS_ROOT
    / "atlas_relation_identity_source_evidence_enrichment_s139_20260602"
    / "atlas_relation_identity_source_evidence_enrichment.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_disposition_recommendation_s140_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_DISPOSITION_RECOMMENDATION_S140_20260602.md"
CURRENT_STORY_ID = "S140"

GENERIC_TOKENS = {
    "dj",
    "mc",
    "live",
    "set",
    "b2b",
    "backtoback",
    "support",
    "guest",
    "resident",
}


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


def token(value: Any) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").casefold())


def latin_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def display_name_tokens(names: list[Any]) -> list[str]:
    return [token(name) for name in names if token(name)]


def has_dotted_variant(names: list[Any]) -> bool:
    texts = [str(name or "") for name in names]
    return any("." in text or "·" in text or "~" in text or "-" in text or " " in text for text in texts)


def has_clear_ascii_spacing_variant(names: list[Any]) -> bool:
    tokens = {latin_token(name) for name in names if latin_token(name)}
    return len(tokens) == 1 and bool(tokens)


def source_titles(row: dict[str, Any]) -> list[str]:
    titles: list[str] = []
    for candidate in as_list(row.get("source_ref_candidates")):
        if isinstance(candidate, dict):
            for field in ["source_title", "evidence_event_title"]:
                value = str(candidate.get(field) or "").strip()
                if value:
                    titles.append(value)
    return titles


def sources_mention_names(row: dict[str, Any]) -> bool:
    names = [str(name or "").strip() for name in as_list(row.get("display_names")) if str(name or "").strip()]
    if not names:
        return False
    haystack = "\n".join(source_titles(row)).casefold()
    name_hits = 0
    for name in names:
        raw = name.casefold()
        compact = latin_token(name)
        if raw and raw in haystack:
            name_hits += 1
            continue
        if compact and compact in latin_token(haystack):
            name_hits += 1
    return name_hits >= min(2, len(names))


def classify_row(row: dict[str, Any]) -> tuple[str, str, list[str], bool]:
    names = as_list(row.get("display_names"))
    tokens = display_name_tokens(names)
    unique_tokens = sorted(set(tokens))
    all_ids = as_list(row.get("all_dj_ids"))
    source_candidates = int((row.get("field_presence") or {}).get("source_ref_candidates") or 0)
    ids_with_source = int((row.get("field_presence") or {}).get("dj_ids_with_source_ref") or 0)
    all_ids_count = int((row.get("field_presence") or {}).get("all_dj_ids") or len(all_ids))
    reason_codes = [str(item) for item in as_list(row.get("source_identity_fields", {}).get("reason_codes"))]
    reasons: list[str] = []
    if source_candidates <= 0:
        return "needs_more_evidence", "no source_ref candidates in sampled DB3 evidence", ["missing_source_ref"], False
    if ids_with_source < all_ids_count:
        return (
            "needs_more_evidence",
            "not every candidate DJ id has source_ref-backed event evidence",
            ["incomplete_source_ref_coverage"],
            False,
        )
    if any(item in GENERIC_TOKENS for item in unique_tokens):
        reasons.append("generic_identity_token")
    if len(unique_tokens) > 1 and not has_clear_ascii_spacing_variant(names):
        reasons.append("name_tokens_not_identical_after_compaction")
    if "collective_or_lineup_label" in reason_codes:
        reasons.append("lineup_or_collective_reason_code")
    if row.get("city_key") in {"", None, "_"}:
        reasons.append("missing_city_key")
    if len(all_ids) >= 5:
        reasons.append("many_ids_in_group")
    if not sources_mention_names(row):
        reasons.append("source_titles_do_not_cover_multiple_name_variants")

    if "generic_identity_token" in reasons:
        return (
            "needs_more_evidence",
            "generic token such as DJ/MC cannot be merged from source_ref coverage alone",
            reasons,
            False,
        )
    if "lineup_or_collective_reason_code" in reasons:
        return (
            "collective_or_lineup_not_dj",
            "source review classified this as possible lineup/collective/generic role",
            reasons,
            False,
        )
    if "name_tokens_not_identical_after_compaction" in reasons:
        return (
            "needs_more_evidence",
            "display-name variants do not collapse to one compact token",
            reasons,
            False,
        )
    if "source_titles_do_not_cover_multiple_name_variants" in reasons:
        return (
            "needs_more_evidence",
            "source titles sampled do not visibly cover multiple variants",
            reasons,
            False,
        )
    if "missing_city_key" in reasons and len(all_ids) > 2:
        return (
            "needs_more_evidence",
            "missing city plus multiple ids requires manual source review",
            reasons,
            False,
        )
    if "many_ids_in_group" in reasons:
        return (
            "merge_candidate_needs_human_signoff",
            "many spelling variants look compact-equivalent but group size requires human signoff",
            reasons,
            True,
        )
    if has_clear_ascii_spacing_variant(names) or has_dotted_variant(names):
        return (
            "merge_candidate_needs_human_signoff",
            "name variants compact to the same token and all ids have source_ref evidence",
            reasons or ["compact_name_variant_with_source_refs"],
            True,
        )
    return (
        "needs_more_evidence",
        "no deterministic recommendation rule matched",
        reasons or ["no_matching_rule"],
        False,
    )


def build_row(row: dict[str, Any]) -> dict[str, Any]:
    recommendation, rationale, reasons, candidate = classify_row(row)
    return {
        "recommendation_row_id": f"s140:{row.get('workbench_row_id', row.get('review_order', 'row'))}",
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
        "source_ref_candidate_count": int((row.get("field_presence") or {}).get("source_ref_candidates") or 0),
        "all_ids_source_ref_coverage": {
            "with_source_ref": int((row.get("field_presence") or {}).get("dj_ids_with_source_ref") or 0),
            "all_ids": int((row.get("field_presence") or {}).get("all_dj_ids") or 0),
        },
        "recommendation": recommendation,
        "recommendation_rationale": rationale,
        "review_flags": reasons,
        "could_feed_disposition_after_human_signoff": candidate,
        "suggested_disposition": (
            "merge_to_canonical_after_source_backing"
            if recommendation == "merge_candidate_needs_human_signoff"
            else "needs_more_evidence"
        ),
        "ready_for_validation": False,
        "approved_for_write_gate": False,
        "write_gate_candidate": False,
        "safe_automerge": False,
        "database_write_allowed": False,
    }


def build_report(source_evidence_path: Path) -> dict[str, Any]:
    source = read_json(source_evidence_path)
    rows = [build_row(row) for row in as_list(source.get("enriched_rows")) if isinstance(row, dict)]
    recommendation_counts = Counter(row["recommendation"] for row in rows)
    candidate_count = sum(1 for row in rows if row["could_feed_disposition_after_human_signoff"])
    return {
        "schema_version": "atlas_relation_identity_disposition_recommendation.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "current_story_id": CURRENT_STORY_ID,
        "decision": "atlas_relation_identity_disposition_recommendation_ready_report_only",
        "source_evidence_enrichment": rel_path(source_evidence_path),
        "source_evidence_decision": source.get("decision"),
        "recommendation_row_count": len(rows),
        "recommendation_counts": dict(sorted(recommendation_counts.items())),
        "could_feed_disposition_after_human_signoff_count": candidate_count,
        "ready_for_validation_count": 0,
        "approved_for_write_gate_count": 0,
        "write_gate_candidate_count": 0,
        "database_write_allowed": False,
        "safe_automerge_allowed": False,
        "recommendation_rows": rows,
        "rules": [
            "Recommendations are not approvals.",
            "Generic tokens such as DJ/MC are not mergeable from token/source_ref coverage alone.",
            "Rows marked merge_candidate_needs_human_signoff still require an approved disposition packet before any write gate.",
            "No row can become ready_for_validation, approved_for_write_gate, or write_gate_candidate in this report.",
        ],
        "safety": {
            "report_only": True,
            "database_mutations": False,
            "identity_merge_executed": False,
            "write_gate_authorized": False,
            "provider_or_llm_call": False,
            "deploy_upload_review": False,
            "secret_read": False,
            "release_rebuild": False,
            "service_restart": False,
            "broad_disk_scan": False,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Atlas Relation Identity Disposition Recommendation S140",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Source evidence: `{report['source_evidence_enrichment']}`",
        f"- Recommendation rows: `{report['recommendation_row_count']}`",
        f"- Human-signoff merge candidates: `{report['could_feed_disposition_after_human_signoff_count']}`",
        f"- Ready / approved / write-candidate: `{report['ready_for_validation_count']}/{report['approved_for_write_gate_count']}/{report['write_gate_candidate_count']}`",
        "",
        "## Recommendation Counts",
        "",
    ]
    for key, value in report["recommendation_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Rows",
            "",
            "| Order | Group | Names | Recommendation | Reason |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in report["recommendation_rows"]:
        names = ", ".join(str(name) for name in row["display_names"][:5]).replace("|", "\\|")
        lines.append(
            f"| `{row['review_order']}` | `{row['group_id']}` | {names} | "
            f"`{row['recommendation']}` | {row['recommendation_rationale'].replace('|', '/')} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Report-only. No row is ready for validation, approved for write gate, or write-gate candidate. No DB write, merge, deploy, upload, provider/model call, secret read, release rebuild, service restart, or broad disk scan occurred.",
            "",
        ]
    )
    return "\n".join(lines)


def render_html(report: dict[str, Any]) -> str:
    rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(row['review_order']))}</td>"
        f"<td>{html.escape(str(row['group_id']))}</td>"
        f"<td>{html.escape(', '.join(str(name) for name in row['display_names'][:5]))}</td>"
        f"<td>{html.escape(row['recommendation'])}</td>"
        f"<td>{html.escape(row['recommendation_rationale'])}</td>"
        "</tr>"
        for row in report["recommendation_rows"]
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Atlas Relation Identity S140 Recommendation</title>
  <style>
    body {{ margin: 0; font-family: Segoe UI, Microsoft YaHei, Arial, sans-serif; background: #f6f8fb; color: #1f2933; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px 22px 48px; }}
    h1 {{ margin: 0 0 8px; font-size: 26px; }}
    .meta {{ color: #667085; margin-bottom: 18px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d9dee7; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid #d9dee7; text-align: left; font-size: 13px; vertical-align: top; }}
    th {{ background: #eef2f6; }}
    code {{ background: #eef2f6; border: 1px solid #d9dee7; border-radius: 4px; padding: 1px 5px; }}
  </style>
</head>
<body>
  <main>
    <h1>Atlas Relation Identity S140 Recommendation</h1>
    <div class="meta">Decision: <code>{html.escape(report['decision'])}</code></div>
    <table>
      <thead><tr><th>Order</th><th>Group</th><th>Names</th><th>Recommendation</th><th>Reason</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </main>
</body>
</html>
"""


def write_reports(report: dict[str, Any], out_dir: Path, scorecard_path: Path | None) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "atlas_relation_identity_disposition_recommendation_s140.json"
    rows_path = out_dir / "atlas_relation_identity_disposition_recommendation_rows_s140.jsonl"
    md_path = out_dir / "atlas_relation_identity_disposition_recommendation_s140.md"
    html_path = out_dir / "atlas_relation_identity_disposition_recommendation_s140.html"
    markdown = render_markdown(report)
    write_json(json_path, report)
    write_jsonl(rows_path, report["recommendation_rows"])
    md_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")
    paths = {"json": str(json_path), "rows": str(rows_path), "markdown": str(md_path), "html": str(html_path)}
    if scorecard_path is not None:
        scorecard_path.parent.mkdir(parents=True, exist_ok=True)
        scorecard_path.write_text(markdown, encoding="utf-8")
        paths["scorecard"] = str(scorecard_path)
    return paths


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-evidence", type=Path, default=DEFAULT_SOURCE_EVIDENCE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--no-scorecard", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_report(args.source_evidence)
    paths = write_reports(report, args.out_dir, None if args.no_scorecard else args.scorecard)
    if args.json_only:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "decision": report["decision"],
                    "recommendation_row_count": report["recommendation_row_count"],
                    "recommendation_counts": report["recommendation_counts"],
                    "could_feed_disposition_after_human_signoff_count": report[
                        "could_feed_disposition_after_human_signoff_count"
                    ],
                    "approved_for_write_gate_count": report["approved_for_write_gate_count"],
                    "write_gate_candidate_count": report["write_gate_candidate_count"],
                    "json": paths["json"],
                    "rows": paths["rows"],
                    "markdown": paths["markdown"],
                    "html": paths["html"],
                    "scorecard": paths.get("scorecard"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
