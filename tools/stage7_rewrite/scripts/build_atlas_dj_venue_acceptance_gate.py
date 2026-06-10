#!/usr/bin/env python3
"""Build a report-only acceptance gate for Atlas DJ venue candidates."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_atlas_dj_venue_work_order_sidecar import norm, read_jsonl, write_json, write_jsonl  # noqa: E402
from build_atlas_event_time_normalized_sidecar import now_iso, text  # noqa: E402
from build_atlas_serving_read_model import event_public_id, row_dict  # noqa: E402


DEFAULT_AUTO_CANDIDATES = (
    REPO_ROOT
    / "reports"
    / "atlas_dj_venue_work_order_sidecar_activity_current_20260525_1708"
    / "venue_auto_candidates.jsonl"
)
DEFAULT_SOURCE_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435"
    / "atlas.sqlite"
)
DEFAULT_SERVING_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_serving_activity_current_time_dedupe_strict_20260525-1625"
    / "atlas_serving.sqlite"
)
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_dj_venue_acceptance_gate_20260525"


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_source_event(conn: sqlite3.Connection, article_uid: str, event_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
          ev.row_pk,
          ev.evid,
          ev.name,
          ev.place,
          ev.time_iso,
          ev.time_text,
          ev.source_article_uid,
          a.title AS source_title,
          a.source_account
        FROM events ev
        LEFT JOIN articles a ON a.article_uid = ev.source_article_uid
        WHERE ev.source_article_uid = ? AND ev.evid = ?
        LIMIT 1
        """,
        (article_uid, event_id),
    ).fetchone()
    return row_dict(row) if row else None


def fetch_serving_event(conn: sqlite3.Connection, serving_event_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM performance_event WHERE event_id = ? LIMIT 1",
        (serving_event_id,),
    ).fetchone()
    return row_dict(row) if row else None


def dj_event_blank_venue_count(conn: sqlite3.Connection, serving_event_id: str) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM dj_event WHERE event_id = ? AND COALESCE(venue_id, '') = ''",
            (serving_event_id,),
        ).fetchone()[0]
    )


def venue_status(candidate: dict[str, Any], source_event: dict[str, Any] | None, serving_event: dict[str, Any] | None) -> str:
    candidate_venue_id = text(candidate.get("candidate_venue_id"))
    candidate_venue_name = text(candidate.get("candidate_venue_name"))
    if not candidate_venue_id or not candidate_venue_name:
        return "blocked_candidate_missing_venue"
    if source_event is None:
        return "blocked_source_event_not_found"
    if serving_event is None:
        return "blocked_serving_event_not_found"

    current_venue_id = text(serving_event.get("venue_id"))
    current_venue_name = text(serving_event.get("venue_name"))
    if current_venue_id == candidate_venue_id:
        if not current_venue_name or norm(current_venue_name) == norm(candidate_venue_name):
            return "already_matching"
        return "blocked_existing_venue_name_conflict"
    if current_venue_id:
        return "blocked_existing_venue_id_conflict"
    if current_venue_name and norm(current_venue_name) not in {
        norm(candidate_venue_name),
        norm(candidate.get("source_account")),
    }:
        return "blocked_existing_venue_name_conflict"
    return "accepted_patch_candidate"


def build_venue_acceptance_gate(
    auto_candidates_path: Path,
    source_db: Path,
    serving_db: Path,
    out_dir: Path,
) -> dict[str, Any]:
    candidates = read_jsonl(auto_candidates_path)
    patch_rows: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    status_counts = Counter()
    venue_counts = Counter()

    source_conn = connect_readonly(source_db)
    serving_conn = connect_readonly(serving_db)
    try:
        for candidate in candidates:
            source_event = fetch_source_event(
                source_conn,
                text(candidate.get("article_uid")),
                text(candidate.get("event_id")),
            )
            serving_event_id = event_public_id(source_event) if source_event else ""
            serving_event = fetch_serving_event(serving_conn, serving_event_id) if serving_event_id else None
            status = venue_status(candidate, source_event, serving_event)
            status_counts[status] += 1
            if status == "accepted_patch_candidate":
                venue_counts[text(candidate.get("candidate_venue_name"))] += 1
            row = {
                "schema_version": "atlas_dj_venue_acceptance_gate.row.v1",
                "work_item_id": text(candidate.get("work_item_id")),
                "article_uid": text(candidate.get("article_uid")),
                "source_event_id": text(candidate.get("event_id")),
                "serving_event_id": serving_event_id,
                "event_name": text(candidate.get("event_name")),
                "source_account": text(candidate.get("source_account")),
                "current_venue_id": text((serving_event or {}).get("venue_id")),
                "current_venue_name": text((serving_event or {}).get("venue_name")),
                "proposed_venue_id": text(candidate.get("candidate_venue_id")),
                "proposed_venue_name": text(candidate.get("candidate_venue_name")),
                "proposed_city": text(candidate.get("candidate_city")),
                "match_kind": text(candidate.get("match_kind")),
                "confidence": candidate.get("confidence"),
                "status": status,
                "dj_event_blank_venue_rows_impacted": (
                    dj_event_blank_venue_count(serving_conn, serving_event_id)
                    if status == "accepted_patch_candidate"
                    else 0
                ),
                "serving_rebuild_executed": False,
                "write_status": "report_only",
            }
            all_rows.append(row)
            if status == "accepted_patch_candidate":
                patch_rows.append(row)
            elif status.startswith("blocked_"):
                blocked_rows.append(row)
    finally:
        source_conn.close()
        serving_conn.close()

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "summary_json": str(out_dir / "summary.json"),
        "summary_md": str(out_dir / "summary.md"),
        "all_rows_jsonl": str(out_dir / "venue_acceptance_gate_rows.jsonl"),
        "patch_candidates_jsonl": str(out_dir / "venue_patch_candidates.jsonl"),
        "blocked_rows_jsonl": str(out_dir / "venue_acceptance_blocked.jsonl"),
    }
    write_jsonl(out_dir / "venue_acceptance_gate_rows.jsonl", all_rows)
    write_jsonl(out_dir / "venue_patch_candidates.jsonl", patch_rows)
    write_jsonl(out_dir / "venue_acceptance_blocked.jsonl", blocked_rows)

    summary = {
        "schema_version": "atlas_dj_venue_acceptance_gate.summary.v1",
        "generated_at": now_iso(),
        "auto_candidates": str(auto_candidates_path),
        "source_db": str(source_db),
        "serving_db": str(serving_db),
        "out_dir": str(out_dir),
        "counts": {
            "input_rows": len(candidates),
            "patch_candidates": len(patch_rows),
            "blocked_rows": len(blocked_rows),
            "dj_event_blank_venue_rows_impacted": sum(
                int(row["dj_event_blank_venue_rows_impacted"]) for row in patch_rows
            ),
        },
        "status_counts": dict(sorted(status_counts.items())),
        "top_patch_venues": [
            {"proposed_venue_name": name, "count": count}
            for name, count in venue_counts.most_common(20)
        ],
        "decision": {
            "status": "atlas_dj_venue_acceptance_patch_ready_report_only"
            if patch_rows
            else "atlas_dj_venue_acceptance_no_patch_candidates_report_only",
            "serving_rebuild_triggered": False,
            "reason": "Venue patch candidates are report-only; a separate serving candidate build must apply and verify them.",
        },
        "outputs": outputs,
        "safety": {
            "llm_call_executed": False,
            "network_call_executed": False,
            "neo4j_write_executed": False,
            "paid_api_call_executed": False,
            "production_write_executed": False,
            "qdrant_write_executed": False,
            "report_only": True,
            "serving_sqlite_rebuild_executed": False,
            "serving_sqlite_write_executed": False,
            "source_sqlite_write_executed": False,
        },
    }
    write_json(out_dir / "summary.json", summary)
    (out_dir / "summary.md").write_text(build_summary_md(summary), encoding="utf-8")
    return {"summary": summary, "rows": all_rows, "patch_rows": patch_rows, "blocked_rows": blocked_rows}


def build_summary_md(summary: dict[str, Any]) -> str:
    lines = [
        "# Atlas DJ Venue Acceptance Gate",
        "",
        f"- Generated at: {summary['generated_at']}",
        f"- Auto candidates: `{summary['auto_candidates']}`",
        f"- Source DB: `{summary['source_db']}`",
        f"- Serving DB: `{summary['serving_db']}`",
        f"- Input rows: {summary['counts']['input_rows']}",
        f"- Patch candidates: {summary['counts']['patch_candidates']}",
        f"- Blocked rows: {summary['counts']['blocked_rows']}",
        f"- DJ-event blank venue rows impacted: {summary['counts']['dj_event_blank_venue_rows_impacted']}",
        f"- Decision: {summary['decision']['status']}",
        f"- Reason: {summary['decision']['reason']}",
        "",
        "## Status Counts",
    ]
    for status, count in sorted(summary["status_counts"].items()):
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Top Patch Venues"])
    for row in summary["top_patch_venues"]:
        lines.append(f"- {row['proposed_venue_name']}: {row['count']}")
    lines.extend(["", "## Outputs"])
    for name, path in sorted(summary["outputs"].items()):
        lines.append(f"- {name}: `{path}`")
    lines.extend(["", "## Safety"])
    for key, value in sorted(summary["safety"].items()):
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auto-candidates", type=Path, default=DEFAULT_AUTO_CANDIDATES)
    parser.add_argument("--source-db", type=Path, default=DEFAULT_SOURCE_DB)
    parser.add_argument("--serving-db", type=Path, default=DEFAULT_SERVING_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_venue_acceptance_gate(args.auto_candidates, args.source_db, args.serving_db, args.out_dir)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
