#!/usr/bin/env python3
"""Build a report-only acceptance gate for venue alias and lineage follow-up rows."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_atlas_dj_venue_alias_lineage_followup_packet import display_path, reject_d_path, stable_id  # noqa: E402
from build_atlas_dj_venue_work_order_sidecar import norm, read_jsonl, write_json, write_jsonl  # noqa: E402
from build_atlas_event_time_normalized_sidecar import now_iso, text  # noqa: E402
from build_atlas_serving_read_model import row_dict  # noqa: E402


DEFAULT_FOLLOWUP_DIR = REPO_ROOT / "reports" / "atlas_dj_venue_alias_lineage_followup_activity_current_20260525_2009"
DEFAULT_ALIAS_CANDIDATES = DEFAULT_FOLLOWUP_DIR / "alias_candidates.jsonl"
DEFAULT_LINEAGE_WORK_ORDER = DEFAULT_FOLLOWUP_DIR / "lineage_work_order.jsonl"
DEFAULT_SERVING_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_serving_activity_current_time_dedupe_strict_20260525-1625"
    / "atlas_serving.sqlite"
)
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_dj_venue_alias_lineage_acceptance_gate_activity_current_20260525_2111"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_VENUE_ALIAS_LINEAGE_ACCEPTANCE_GATE_20260525.md"

URL_OR_ARCHIVE_RE = re.compile(r"https?://|mp\.weixin|raw\.html|archive_", re.IGNORECASE)
SECRET_WORD_RE = re.compile(r"\b(openid|fakeid|unionid|secret|token|cookie|password)\b", re.IGNORECASE)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.IGNORECASE,
)


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_serving_event(conn: sqlite3.Connection, event_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM performance_event WHERE event_id = ? LIMIT 1",
        (event_id,),
    ).fetchone()
    return row_dict(row) if row else None


def dj_event_blank_venue_count(conn: sqlite3.Connection, event_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM dj_event WHERE event_id = ? AND COALESCE(venue_id, '') = ''",
        (event_id,),
    ).fetchone()
    return int(row[0] if row else 0)


def public_leak_counts(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
        counts["url_or_archive_hits"] += len(URL_OR_ARCHIVE_RE.findall(payload))
        counts["secret_word_hits"] += len(SECRET_WORD_RE.findall(payload))
        counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(payload))
    return dict(counts)


def build_alias_acceptance_rows(rows: list[dict[str, Any]], generated_at: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_rows: list[dict[str, Any]] = []
    accepted_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        normalized_name_match = bool(row.get("normalized_name_match"))
        current_venue_id = text(row.get("current_venue_id"))
        proposed_venue_id = text(row.get("proposed_venue_id"))
        current_names = [text(value) for value in row.get("current_venue_name_variants") or []]
        proposed_names = [text(value) for value in row.get("proposed_venue_name_variants") or []]
        has_required_fields = bool(current_venue_id and proposed_venue_id and proposed_names)
        if normalized_name_match and has_required_fields and current_venue_id != proposed_venue_id:
            status = "alias_map_review_ready_report_only"
            blocker = ""
        else:
            status = "blocked_alias_candidate_incomplete_or_ambiguous"
            blocker = "Alias candidate lacks normalized-name match, required ids/names, or differs insufficiently for alias-map review."
        candidate = {
            "schema_version": "atlas_dj_venue_alias_lineage_acceptance_gate.alias_row.v1",
            "generated_at": generated_at,
            "input_index": index,
            "alias_candidate_id": text(row.get("alias_candidate_id")),
            "current_venue_id": current_venue_id,
            "current_venue_name": text(row.get("current_venue_name")),
            "current_venue_name_variants": current_names,
            "proposed_venue_id": proposed_venue_id,
            "proposed_venue_name": text(row.get("proposed_venue_name")),
            "proposed_venue_name_variants": proposed_names,
            "proposed_city": text(row.get("proposed_city")),
            "row_count": int(row.get("row_count") or 0),
            "normalized_name_match": normalized_name_match,
            "status": status,
            "alias_map_write_allowed": False,
            "serving_patch_eligible": False,
            "serving_patch_blocker": blocker or "Alias-map review is not a serving SQLite patch by itself.",
            "write_status": "report_only",
        }
        all_rows.append(candidate)
        if status == "alias_map_review_ready_report_only":
            accepted_rows.append(candidate)
    return all_rows, accepted_rows


def lineage_status(row: dict[str, Any], serving_event: dict[str, Any] | None) -> str:
    proposed_venue_id = text(row.get("proposed_venue_id"))
    proposed_venue_name = text(row.get("proposed_venue_name"))
    if not text(row.get("serving_event_id")):
        return "blocked_missing_serving_event_id"
    if not proposed_venue_id or not proposed_venue_name:
        return "blocked_missing_proposed_venue"
    if serving_event is None:
        return "blocked_selected_serving_event_not_found"
    current_venue_id = text(serving_event.get("venue_id"))
    current_venue_name = text(serving_event.get("venue_name"))
    if current_venue_id == proposed_venue_id:
        return "already_matching"
    if current_venue_id:
        return "blocked_existing_venue_id_conflict"
    if current_venue_name and norm(current_venue_name) not in {norm(proposed_venue_name), norm(row.get("source_account"))}:
        return "blocked_existing_venue_name_conflict"
    return "accepted_lineage_patch_candidate_report_only"


def build_lineage_acceptance_rows(
    rows: list[dict[str, Any]],
    serving_db: Path,
    generated_at: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    all_rows: list[dict[str, Any]] = []
    patch_rows: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []

    conn = connect_readonly(serving_db)
    try:
        for index, row in enumerate(rows, start=1):
            serving_event_id = text(row.get("serving_event_id"))
            serving_event = fetch_serving_event(conn, serving_event_id) if serving_event_id else None
            status = lineage_status(row, serving_event)
            blank_dj_rows = (
                dj_event_blank_venue_count(conn, serving_event_id)
                if status == "accepted_lineage_patch_candidate_report_only"
                else 0
            )
            candidate = {
                "schema_version": "atlas_dj_venue_alias_lineage_acceptance_gate.lineage_row.v1",
                "generated_at": generated_at,
                "input_index": index,
                "lineage_work_order_id": text(row.get("lineage_work_order_id")),
                "article_uid": text(row.get("article_uid")),
                "source_event_id": text(row.get("source_event_id")),
                "serving_event_id": serving_event_id,
                "event_name": text(row.get("event_name")),
                "source_account": text(row.get("source_account")),
                "current_venue_id": text((serving_event or {}).get("venue_id")),
                "current_venue_name": text((serving_event or {}).get("venue_name")),
                "proposed_venue_id": text(row.get("proposed_venue_id")),
                "proposed_venue_name": text(row.get("proposed_venue_name")),
                "proposed_city": text(row.get("proposed_city")),
                "status": status,
                "dj_event_blank_venue_rows_impacted": blank_dj_rows,
                "serving_patch_eligible": status == "accepted_lineage_patch_candidate_report_only",
                "serving_patch_blocker": ""
                if status == "accepted_lineage_patch_candidate_report_only"
                else "Selected serving event is missing or already has conflicting venue state.",
                "write_status": "report_only",
            }
            all_rows.append(candidate)
            if status == "accepted_lineage_patch_candidate_report_only":
                patch_rows.append(candidate)
            elif status.startswith("blocked_"):
                blocked_rows.append(candidate)
    finally:
        conn.close()
    return all_rows, patch_rows, blocked_rows


def build_summary_md(summary: dict[str, Any]) -> str:
    lines = [
        "# Atlas DJ Venue Alias / Lineage Acceptance Gate",
        "",
        f"- Generated at: {summary['generated_at']}",
        f"- Decision: {summary['decision']['status']}",
        f"- Alias input groups: {summary['counts']['alias_input_groups']}",
        f"- Alias map review-ready groups: {summary['counts']['alias_map_review_ready_groups']}",
        f"- Lineage input rows: {summary['counts']['lineage_input_rows']}",
        f"- Lineage patch candidates: {summary['counts']['lineage_patch_candidates']}",
        f"- Serving patch candidates: {summary['counts']['serving_patch_candidates']}",
        "",
        "## Status Counts",
    ]
    for key, value in sorted(summary["status_counts"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Outputs"])
    for name, path in sorted(summary["outputs"].items()):
        lines.append(f"- {name}: `{path}`")
    lines.extend(["", "## Safety"])
    for key, value in sorted(summary["safety"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Public Leak Scan"])
    for key, value in sorted(summary["public_leak_scan"].items()):
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def build_report_md(summary: dict[str, Any]) -> str:
    lines = [
        "# ATLAS T5 Venue Alias / Lineage Acceptance Gate",
        "",
        f"Generated: {summary['generated_at']}",
        "",
        "## Result",
        "",
        f"- Decision: `{summary['decision']['status']}`.",
        f"- Alias input groups: `{summary['counts']['alias_input_groups']}`.",
        f"- Alias map review-ready groups: `{summary['counts']['alias_map_review_ready_groups']}`.",
        f"- Lineage input rows: `{summary['counts']['lineage_input_rows']}`.",
        f"- Lineage patch candidates: `{summary['counts']['lineage_patch_candidates']}`.",
        f"- Serving patch candidates: `{summary['counts']['serving_patch_candidates']}`.",
        "",
        "## Interpretation",
        "",
        "- Alias groups are review-ready only for a future alias-map decision; this gate does not write an alias map or serving SQLite.",
        "- Lineage rows are checked against the selected serving DB read-only before any patch candidate can exist.",
        "- No serving rebuild is warranted unless a future gate accepts concrete patch rows and rollback/post-write checks.",
        "",
        "## Boundary",
        "",
        "- Report-only acceptance gate.",
        "- No source/raw Atlas DB mutation.",
        "- No serving SQLite rebuild or write.",
        "- No alias-map write.",
        "- No public pointer, CloudRun/VPS deploy, Neo4j/Qdrant/SQLite production write, mini-program upload/review, memory write, credential read/print, network/model/paid API call, 9router action, or D: root scan.",
        "",
        "## Evidence",
        "",
    ]
    for name, path in sorted(summary["outputs"].items()):
        lines.append(f"- `{name}`: `{path}`")
    lines.append("")
    return "\n".join(lines)


def build_acceptance_gate(
    alias_candidates_path: Path,
    lineage_work_order_path: Path,
    serving_db: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    for label, path in {
        "alias_candidates": alias_candidates_path,
        "lineage_work_order": lineage_work_order_path,
        "serving_db": serving_db,
        "out_dir": out_dir,
        "report_path": report_path,
    }.items():
        reject_d_path(path, label)

    alias_rows = read_jsonl(alias_candidates_path)
    lineage_rows = read_jsonl(lineage_work_order_path)
    generated_at = now_iso()
    alias_acceptance_rows, alias_map_rows = build_alias_acceptance_rows(alias_rows, generated_at)
    lineage_acceptance_rows, lineage_patch_rows, lineage_blocked_rows = build_lineage_acceptance_rows(
        lineage_rows,
        serving_db,
        generated_at,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "summary_json": display_path(out_dir / "summary.json"),
        "summary_md": display_path(out_dir / "summary.md"),
        "report_md": display_path(report_path),
        "alias_acceptance_rows_jsonl": display_path(out_dir / "alias_acceptance_rows.jsonl"),
        "alias_map_review_ready_jsonl": display_path(out_dir / "alias_map_review_ready.jsonl"),
        "lineage_acceptance_rows_jsonl": display_path(out_dir / "lineage_acceptance_rows.jsonl"),
        "lineage_patch_candidates_jsonl": display_path(out_dir / "lineage_patch_candidates.jsonl"),
        "lineage_blocked_rows_jsonl": display_path(out_dir / "lineage_blocked_rows.jsonl"),
    }
    write_jsonl(out_dir / "alias_acceptance_rows.jsonl", alias_acceptance_rows)
    write_jsonl(out_dir / "alias_map_review_ready.jsonl", alias_map_rows)
    write_jsonl(out_dir / "lineage_acceptance_rows.jsonl", lineage_acceptance_rows)
    write_jsonl(out_dir / "lineage_patch_candidates.jsonl", lineage_patch_rows)
    write_jsonl(out_dir / "lineage_blocked_rows.jsonl", lineage_blocked_rows)

    status_counts = Counter(row["status"] for row in [*alias_acceptance_rows, *lineage_acceptance_rows])
    leak_rows = [*alias_acceptance_rows, *alias_map_rows, *lineage_acceptance_rows, *lineage_patch_rows, *lineage_blocked_rows]
    serving_patch_candidates = len(lineage_patch_rows)
    summary = {
        "schema_version": "atlas_dj_venue_alias_lineage_acceptance_gate.summary.v1",
        "generated_at": generated_at,
        "alias_candidates": display_path(alias_candidates_path),
        "lineage_work_order": display_path(lineage_work_order_path),
        "serving_db": display_path(serving_db),
        "out_dir": display_path(out_dir),
        "report": display_path(report_path),
        "counts": {
            "alias_input_groups": len(alias_rows),
            "alias_map_review_ready_groups": len(alias_map_rows),
            "lineage_input_rows": len(lineage_rows),
            "lineage_patch_candidates": len(lineage_patch_rows),
            "lineage_blocked_rows": len(lineage_blocked_rows),
            "serving_patch_candidates": serving_patch_candidates,
            "dj_event_blank_venue_rows_impacted": sum(
                int(row["dj_event_blank_venue_rows_impacted"]) for row in lineage_patch_rows
            ),
        },
        "status_counts": dict(sorted(status_counts.items())),
        "decision": {
            "status": "atlas_dj_venue_alias_lineage_acceptance_patch_ready_report_only"
            if serving_patch_candidates
            else "atlas_dj_venue_alias_lineage_acceptance_no_serving_patch_report_only",
            "serving_rebuild_triggered": False,
            "reason": "Alias groups need a separate alias-map decision and lineage rows need selected-serving event matches before serving can be patched.",
        },
        "outputs": outputs,
        "public_leak_scan": public_leak_counts(leak_rows),
        "safety": {
            "alias_map_write_executed": False,
            "llm_call_executed": False,
            "network_call_executed": False,
            "neo4j_write_executed": False,
            "paid_api_call_executed": False,
            "production_write_executed": False,
            "qdrant_write_executed": False,
            "report_only": True,
            "serving_db_readonly": True,
            "serving_sqlite_rebuild_executed": False,
            "serving_sqlite_write_executed": False,
            "source_sqlite_write_executed": False,
        },
    }
    write_json(out_dir / "summary.json", summary)
    (out_dir / "summary.md").write_text(build_summary_md(summary), encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(build_report_md(summary), encoding="utf-8")
    return {
        "summary": summary,
        "alias_acceptance_rows": alias_acceptance_rows,
        "alias_map_rows": alias_map_rows,
        "lineage_acceptance_rows": lineage_acceptance_rows,
        "lineage_patch_rows": lineage_patch_rows,
        "lineage_blocked_rows": lineage_blocked_rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alias-candidates", type=Path, default=DEFAULT_ALIAS_CANDIDATES)
    parser.add_argument("--lineage-work-order", type=Path, default=DEFAULT_LINEAGE_WORK_ORDER)
    parser.add_argument("--serving-db", type=Path, default=DEFAULT_SERVING_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_acceptance_gate(
        args.alias_candidates,
        args.lineage_work_order,
        args.serving_db,
        args.out_dir,
        args.report,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
