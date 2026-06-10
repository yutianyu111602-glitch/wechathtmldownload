#!/usr/bin/env python3
"""Safe autowake runner for the Atlas DB2/outlink lane.

This runner is deliberately conservative. It wakes up, reads the current
report-only DB2/outlink surfaces, writes heartbeat/evidence files, and stops or
idles when the next action would require a new queue, network fetches, DB
writes, secrets, paid APIs, deployment, or upload.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]

TAKEOVER_REPORT = REPO_ROOT / "reports" / "ATLAS_DB2_OUTLINK_TAKEOVER_20260531.md"
REVIEW_QUEUE_V2 = (
    STAGE7_ROOT
    / "reports"
    / "atlas_entity_public_search_post_filter_full_138102_20260521_v2"
    / "entity_public_search_review_queue.jsonl"
)
BATCH002_SUMMARY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_profile_outlinks_batch002_20260525"
    / "atlas_social_profile_outlinks_summary.json"
)
BATCH002_FETCHES = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_profile_outlinks_batch002_20260525"
    / "atlas_social_profile_fetches.jsonl"
)
BATCH002_OUTLINKS = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_profile_outlinks_batch002_20260525"
    / "atlas_social_profile_outlinks.jsonl"
)
BATCH002_FOLLOWUP = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_profile_outlinks_batch002_20260525"
    / "atlas_social_outlink_followup_queue.jsonl"
)
OVERLAY_DB = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t6_sidecar_new_db_overlay_t5_t6_20260526"
    / "atlas_t6_sidecar_social_overlay.sqlite"
)
MERGE_CONTRACT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t6_sidecar_manifest_validation_gate_t5_t6_20260526"
    / "merge_contract.json"
)
NEXT_WORK_ORDERS = (
    STAGE7_ROOT
    / "reports"
    / "atlas_dj_completion_overlay_rollup_t5_t6_20260527"
    / "dj_completion_next_work_orders.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_db2_outlink_autowake_20260531"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def line_count(path: Path) -> int | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        return sum(1 for _ in handle)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))


def overlay_counts(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False}
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        counts = {
            table: int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in tables
        }
        quick_check = str(conn.execute("PRAGMA quick_check").fetchone()[0])
    finally:
        conn.close()
    return {
        "exists": True,
        "path": display_path(path),
        "size_bytes": int(path.stat().st_size),
        "quick_check": quick_check,
        "tables": tables,
        "counts": counts,
    }


def build_snapshot() -> dict[str, Any]:
    batch_summary = read_json(BATCH002_SUMMARY)
    merge_contract = read_json(MERGE_CONTRACT)
    return {
        "generated_at": now_iso(),
        "takeover_report": {
            "exists": TAKEOVER_REPORT.exists(),
            "path": display_path(TAKEOVER_REPORT),
        },
        "review_queue_v2": {
            "exists": REVIEW_QUEUE_V2.exists(),
            "path": display_path(REVIEW_QUEUE_V2),
            "line_count": line_count(REVIEW_QUEUE_V2),
        },
        "batch002": {
            "summary_exists": BATCH002_SUMMARY.exists(),
            "summary_path": display_path(BATCH002_SUMMARY),
            "summary": batch_summary,
            "fetch_rows": line_count(BATCH002_FETCHES),
            "outlink_rows": line_count(BATCH002_OUTLINKS),
            "followup_rows": line_count(BATCH002_FOLLOWUP),
        },
        "overlay_db": overlay_counts(OVERLAY_DB),
        "merge_contract": {
            "exists": MERGE_CONTRACT.exists(),
            "path": display_path(MERGE_CONTRACT),
            "write_execution_allowed_now": bool(merge_contract.get("write_execution_allowed_now")),
            "source_raw_db_target_required": bool(merge_contract.get("source_raw_db_target_required")),
            "write_guards": merge_contract.get("write_guards", {}),
        },
        "next_work_orders": {
            "exists": NEXT_WORK_ORDERS.exists(),
            "path": display_path(NEXT_WORK_ORDERS),
            "line_count": line_count(NEXT_WORK_ORDERS),
        },
    }


def classify(snapshot: dict[str, Any], allow_network_fetch: bool) -> dict[str, Any]:
    review_lines = snapshot["review_queue_v2"].get("line_count") or 0
    batch_input_rows = int(snapshot["batch002"].get("summary", {}).get("input_rows") or 0)
    overlay = snapshot.get("overlay_db", {})
    merge_contract = snapshot.get("merge_contract", {})

    if not snapshot["takeover_report"].get("exists"):
        return {
            "status": "blocked_missing_takeover_report",
            "health": "BLOCKED",
            "continue_loop": False,
            "reason": "takeover report missing; cannot safely infer current DB2/outlink boundary",
        }
    if review_lines and batch_input_rows >= review_lines and overlay.get("exists"):
        return {
            "status": "idle_waiting_new_queue_or_schema_decision",
            "health": "WARN",
            "continue_loop": True,
            "reason": "current v2 outlink review queue is already covered by batch002; repeating would duplicate work",
        }
    if review_lines and batch_input_rows < review_lines and not allow_network_fetch:
        return {
            "status": "blocked_network_fetch_not_authorized",
            "health": "BLOCKED",
            "continue_loop": False,
            "reason": "new or partially processed outlink queue exists, but network fetching is disabled for this runner",
        }
    if merge_contract.get("write_execution_allowed_now"):
        return {
            "status": "blocked_unexpected_write_gate_open",
            "health": "FAIL",
            "continue_loop": False,
            "reason": "merge contract reports write gate open; require human review before any self-execution",
        }
    return {
        "status": "blocked_insufficient_current_evidence",
        "health": "BLOCKED",
        "continue_loop": False,
        "reason": "required queue, batch summary, or overlay evidence is missing",
    }


def next_actions(snapshot: dict[str, Any], decision: dict[str, Any]) -> list[dict[str, Any]]:
    actions = [
        {
            "priority": 0,
            "action": "do_not_repeat_batch002_without_new_queue_or_cursor",
            "status": "active_guard",
            "evidence": {
                "review_queue_rows": snapshot["review_queue_v2"].get("line_count"),
                "batch002_input_rows": snapshot["batch002"].get("summary", {}).get("input_rows"),
            },
        },
        {
            "priority": 1,
            "action": "decide_db2_social_overlay_strategy",
            "status": "ready_for_human_or_schema_story",
            "evidence": {
                "overlay_db": snapshot["overlay_db"].get("path"),
                "overlay_counts": snapshot["overlay_db"].get("counts", {}),
                "write_execution_allowed_now": snapshot["merge_contract"].get("write_execution_allowed_now"),
            },
        },
        {
            "priority": 2,
            "action": "recover_identity_source_context_and_avatar_media_blockers",
            "status": "report_only_t6_side_work",
            "evidence": {
                "next_work_orders": snapshot["next_work_orders"].get("path"),
                "next_work_orders_rows": snapshot["next_work_orders"].get("line_count"),
            },
        },
    ]
    if decision["status"] == "blocked_network_fetch_not_authorized":
        actions.insert(
            0,
            {
                "priority": -1,
                "action": "rerun_outlink_fetch_only_with_explicit_network_authorization",
                "status": "blocked",
                "evidence": {"allow_network_fetch": False},
            },
        )
    return actions


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def report_markdown(snapshot: dict[str, Any], decision: dict[str, Any], actions: list[dict[str, Any]], cycle: int) -> str:
    overlay_counts_map = snapshot["overlay_db"].get("counts", {})
    batch_summary = snapshot["batch002"].get("summary", {})
    action_lines = "\n".join(
        f"- P{action['priority']}: `{action['action']}` — `{action['status']}`" for action in actions
    )
    return f"""# Atlas DB2 Outlink Autowake Report

Generated: {snapshot['generated_at']}
Cycle: {cycle}

## Decision

- status: `{decision['status']}`
- health: `{decision['health']}`
- reason: {decision['reason']}

## Evidence

- takeover report exists: `{snapshot['takeover_report']['exists']}`
- v2 review queue rows: `{snapshot['review_queue_v2']['line_count']}`
- batch002 input/outlink/follow-up rows: `{batch_summary.get('input_rows')}` / `{snapshot['batch002']['outlink_rows']}` / `{snapshot['batch002']['followup_rows']}`
- overlay DB exists: `{snapshot['overlay_db'].get('exists')}`
- overlay rows: links `{overlay_counts_map.get('atlas_dj_social_links')}`, rollups `{overlay_counts_map.get('atlas_dj_social_entity_rollups')}`, metadata `{overlay_counts_map.get('atlas_overlay_metadata')}`
- write execution allowed now: `{snapshot['merge_contract']['write_execution_allowed_now']}`
- source/raw DB target required: `{snapshot['merge_contract']['source_raw_db_target_required']}`

## Next Actions

{action_lines}

## Safety

This autowake runner did not perform network fetches, source/raw DB writes, serving DB writes, graph/vector writes, memory writes, deployment, upload/review, paid API calls, 9router calls, secret reads, or D-root scans.
"""


def run_cycle(out_dir: Path, cycle: int, allow_network_fetch: bool) -> dict[str, Any]:
    snapshot = build_snapshot()
    decision = classify(snapshot, allow_network_fetch=allow_network_fetch)
    actions = next_actions(snapshot, decision)
    payload = {
        "cycle": cycle,
        "snapshot": snapshot,
        "decision": decision,
        "next_actions": actions,
    }
    write_json(out_dir / "autowake_state.json", payload)
    write_json(out_dir / "HEARTBEAT.json", {
        "last_heartbeat_at": snapshot["generated_at"],
        "health": decision["health"],
        "status": decision["status"],
        "next_resume_cursor": display_path(out_dir / "autowake_state.json"),
    })
    write_jsonl(out_dir / "next_actions.jsonl", actions)
    (out_dir / "autowake_report.md").write_text(
        report_markdown(snapshot, decision, actions, cycle),
        encoding="utf-8",
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-sec", type=float, default=300.0)
    parser.add_argument("--max-cycles", type=int, default=1)
    parser.add_argument("--allow-network-fetch", action="store_true")
    parser.add_argument("--stop-file", type=Path, default=DEFAULT_OUT_DIR / "STOP")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    max_cycles = max(1, int(args.max_cycles))
    for cycle in range(1, max_cycles + 1):
        if args.stop_file.exists():
            write_json(args.out_dir / "HEARTBEAT.json", {
                "last_heartbeat_at": now_iso(),
                "health": "STOPPED",
                "status": "stop_file_present",
                "next_resume_cursor": display_path(args.out_dir / "autowake_state.json"),
            })
            return 0
        payload = run_cycle(args.out_dir, cycle, allow_network_fetch=bool(args.allow_network_fetch))
        if not args.loop:
            return 0
        if cycle < max_cycles and payload["decision"].get("continue_loop"):
            time.sleep(max(1.0, float(args.interval_sec)))
        elif cycle < max_cycles:
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
