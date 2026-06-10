from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_TASKS = (
    REPORTS_ROOT
    / "atlas_relation_db2_source_provider_spool_sidecar_s224_from_s219_20260602"
    / "s224_normalized_source_provider_tasks.jsonl"
)
DEFAULT_EVENTS = (
    REPORTS_ROOT
    / "atlas_relation_identity_db2_source_provider_spool_s225_from_s219_20260602"
    / "s222_db2_writer_identity_candidate_events.jsonl"
)
DEFAULT_S226 = (
    REPORTS_ROOT
    / "atlas_relation_identity_db2_source_provider_spool_live_s226_from_s225_20260602"
    / "atlas_relation_identity_db2_source_provider_spool_live_s226.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_s228_pending_candidate_workbench_20260602"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def per_dj_missing_archive(row: dict[str, Any]) -> bool:
    per_dj = row.get("per_dj_resolution") or {}
    return any(not bool(v.get("has_exact_archive")) for v in per_dj.values() if isinstance(v, dict))


def classify_task(row: dict[str, Any]) -> tuple[str, str]:
    seed = row.get("source_seed") or {}
    common_accounts = seed.get("common_source_accounts") or []
    common_titles = seed.get("common_titles") or []
    common_venues = seed.get("common_venues") or []
    exact_archive_count = int(row.get("exact_archive_ref_count") or 0)
    resolved_count = int(row.get("source_url_resolved_ref_count") or 0)
    has_provider_anchor = bool(seed.get("has_provider_anchor"))

    if exact_archive_count > 0 and per_dj_missing_archive(row):
        return "P1_recover_missing_profile_archive_or_provider", "recover_missing_archive_for_uncovered_profile"
    if common_accounts or has_provider_anchor:
        return "P2_provider_anchor_crosscheck", "provider_crosscheck_by_common_account_or_venue"
    if common_titles:
        return "P2_source_title_crosscheck", "source_title_or_event_title_provider_search"
    if resolved_count > 0:
        return "P2_resolved_source_url_public_or_archive_replay", "resolved_source_ref_replay_or_public_fetch"
    return "P3_external_manual_acquisition", "external_provider_search_required"


def build_workbench(
    tasks: list[dict[str, Any]],
    events: list[dict[str, Any]],
    s226: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    event_by_task = {str(row.get("source_profile_id") or row.get("handle")): row for row in events}
    workbench: list[dict[str, Any]] = []
    next_actions: list[dict[str, Any]] = []
    counters: dict[str, Counter[str]] = {
        "input_route": Counter(),
        "acquisition_strategy": Counter(),
        "priority": Counter(),
        "s228_lane": Counter(),
        "review_status": Counter(),
    }
    joined_count = 0
    safety_findings: list[dict[str, Any]] = []

    for task in tasks:
        task_id = str(task.get("task_id") or "")
        event = event_by_task.get(task_id)
        if event:
            joined_count += 1
        lane, action = classify_task(task)
        review_status = str((event or {}).get("review_status") or "missing_event")
        counters["input_route"][str(task.get("input_route") or "unknown")] += 1
        counters["acquisition_strategy"][str(task.get("acquisition_strategy") or "unknown")] += 1
        counters["priority"][str(task.get("priority") or "unknown")] += 1
        counters["s228_lane"][lane] += 1
        counters["review_status"][review_status] += 1

        if task.get("raw_source_url_emitted") or task.get("raw_archive_path_emitted"):
            safety_findings.append({"task_id": task_id, "finding": "raw_source_or_archive_path_flagged"})

        row = {
            "schema_version": "atlas_relation_identity_s228_pending_candidate_workbench.v1.row",
            "task_id": task_id,
            "group_id": task.get("group_id"),
            "display_names": task.get("display_names") or [],
            "dj_ids": task.get("dj_ids") or [],
            "unicode_compact_values": task.get("unicode_compact_values") or [],
            "input_route": task.get("input_route"),
            "priority": task.get("priority"),
            "acquisition_strategy": task.get("acquisition_strategy"),
            "s228_lane": lane,
            "next_action": action,
            "review_status": review_status,
            "accepted_for_graph": int((event or {}).get("accepted_for_graph") or 0),
            "db3_write_allowed_now": False,
            "db2_projection_allowed_now": False,
            "source_ref_count": int(task.get("source_ref_count") or 0),
            "exact_archive_ref_count": int(task.get("exact_archive_ref_count") or 0),
            "source_url_resolved_ref_count": int(task.get("source_url_resolved_ref_count") or 0),
            "public_fetch_ready_ref_count": int(task.get("public_fetch_ready_ref_count") or 0),
            "source_seed": task.get("source_seed") or {},
            "has_missing_archive_profile": per_dj_missing_archive(task),
            "raw_source_url_emitted": bool(task.get("raw_source_url_emitted")),
            "raw_archive_path_emitted": bool(task.get("raw_archive_path_emitted")),
        }
        workbench.append(row)
        next_actions.append(
            {
                "task_id": task_id,
                "group_id": task.get("group_id"),
                "s228_lane": lane,
                "next_action": action,
                "db3_gate": "blocked_until_article_ready_or_provider_crosschecked_evidence",
            }
        )

    pending_readback = int(((s226.get("readback") or {}).get("after_s222_pending_review")) or 0)
    accepted_readback = int(((s226.get("readback") or {}).get("after_s222_accepted_for_graph")) or 0)
    report = {
        "schema_version": "atlas_relation_identity_s228_pending_candidate_workbench.v1",
        "current_story_id": "S228",
        "generated_at": utc_now(),
        "decision": (
            "atlas_relation_identity_s228_pending_candidate_workbench_ready_report_only"
            if not safety_findings and joined_count == len(tasks) == len(events) == pending_readback and accepted_readback == 0
            else "atlas_relation_identity_s228_pending_candidate_workbench_needs_review"
        ),
        "counts": {
            "task_count": len(tasks),
            "event_count": len(events),
            "joined_task_event_count": joined_count,
            "pending_readback_count": pending_readback,
            "accepted_for_graph_readback_count": accepted_readback,
            "safety_finding_count": len(safety_findings),
            "db3_write_candidate_count": 0,
            "db2_projection_candidate_count": 0,
            "input_route_counts": dict(counters["input_route"]),
            "acquisition_strategy_counts": dict(counters["acquisition_strategy"]),
            "priority_counts": dict(counters["priority"]),
            "s228_lane_counts": dict(counters["s228_lane"]),
            "review_status_counts": dict(counters["review_status"]),
        },
        "safety": {
            "report_only": True,
            "db1_mutation": False,
            "db2_mutation": False,
            "db2_projection": False,
            "db3_mutation": False,
            "deploy_upload_review_release": False,
            "raw_source_url_emitted": False,
            "raw_archive_path_emitted": False,
            "secret_values_printed": False,
            "safety_findings": safety_findings,
        },
        "execution_cursor": {
            "next_story_id": "S228B",
            "next_action": "Run bounded source/provider acquisition for the highest-yield S228 lanes, then feed only article-ready or provider-crosschecked evidence into strict DB3 write gates.",
            "db2_projection_allowed_now": False,
            "db3_write_allowed_now": False,
            "deploy_upload_review_release_allowed_now": False,
        },
    }
    return report, workbench, next_actions


def render_markdown(report: dict[str, Any], out_json: Path) -> str:
    counts = report["counts"]
    lanes = counts["s228_lane_counts"]
    lines = [
        "# Atlas Relation Identity S228 Pending Candidate Workbench",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"Decision: `{report['decision']}`",
        "",
        "## Counts",
        "",
        f"- task_count: `{counts['task_count']}`",
        f"- event_count: `{counts['event_count']}`",
        f"- joined_task_event_count: `{counts['joined_task_event_count']}`",
        f"- pending_readback_count: `{counts['pending_readback_count']}`",
        f"- accepted_for_graph_readback_count: `{counts['accepted_for_graph_readback_count']}`",
        f"- db3_write_candidate_count: `{counts['db3_write_candidate_count']}`",
        f"- db2_projection_candidate_count: `{counts['db2_projection_candidate_count']}`",
        "",
        "## S228 Lanes",
        "",
    ]
    for key, value in sorted(lanes.items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This workbench is report-only. It does not mutate DB1, DB2, or DB3, does not project DB2, does not deploy/upload/review/release, and does not emit raw source URLs or archive paths.",
            "",
            "## Next",
            "",
            report["execution_cursor"]["next_action"],
            "",
            "## Artifact",
            "",
            f"- `{rel(out_json)}`",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--s226-report", type=Path, default=DEFAULT_S226)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    tasks = read_jsonl(args.tasks)
    events = read_jsonl(args.events)
    s226 = read_json(args.s226_report)
    report, workbench, next_actions = build_workbench(tasks, events, s226)

    out_dir = args.out_dir
    report_path = out_dir / "atlas_relation_identity_s228_pending_candidate_workbench.json"
    workbench_path = out_dir / "s228_pending_candidate_workbench.jsonl"
    next_actions_path = out_dir / "s228_next_actions.jsonl"
    markdown_path = out_dir / "atlas_relation_identity_s228_pending_candidate_workbench.md"

    report["artifacts"] = {
        "report_json": rel(report_path),
        "workbench_jsonl": rel(workbench_path),
        "next_actions_jsonl": rel(next_actions_path),
        "markdown": rel(markdown_path),
    }
    write_json(report_path, report)
    write_jsonl(workbench_path, workbench)
    write_jsonl(next_actions_path, next_actions)
    markdown_path.write_text(render_markdown(report, report_path), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
