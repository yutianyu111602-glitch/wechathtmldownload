#!/usr/bin/env python3
"""Reconcile the user-command ledger with the latest Weekly/Atlas blockers.

Report-only. This script only reads the historical command ledger and existing
audit artifacts. It does not run OpenClaw or weekly pipelines, call map
providers or LLMs, launch DevTools, deploy, upload, submit review, read
secrets, write coordinates, mutate databases, rebuild releases, restart
services, or scan broad disks.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_LEDGER = REPO_ROOT / "reports" / "WEEKLY_USER_COMMAND_RECALL_EXECUTION_LEDGER_20260531.md"
DEFAULT_GOAL_COMPLETION = (
    REPORTS_ROOT
    / "weekly_goal_completion_audit_s114_20260601"
    / "weekly_goal_completion_audit.json"
)
DEFAULT_REMAINING_BLOCKERS = (
    REPORTS_ROOT
    / "weekly_remaining_blocker_closure_audit_s113_20260601"
    / "weekly_remaining_blocker_closure_audit.json"
)
DEFAULT_DEPLOY_PREFLIGHT = (
    REPORTS_ROOT
    / "weekly_deploy_preflight_blocker_next_action_packet_s112_20260601"
    / "weekly_deploy_preflight_blocker_next_action_packet.json"
)
DEFAULT_RELATION_IDENTITY = (
    REPORTS_ROOT
    / "atlas_relation_identity_write_blocker_audit_s111_20260601"
    / "atlas_relation_identity_write_blocker_audit.json"
)
DEFAULT_COORDINATE = (
    REPORTS_ROOT
    / "weekly_coordinate_write_blocker_audit_s109_20260601"
    / "weekly_coordinate_write_blocker_audit.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_user_command_ledger_current_status_s114_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_USER_COMMAND_LEDGER_CURRENT_STATUS_S114_20260601.md"

CURRENT_STORY_ID = "S114"
SOURCE_STORY_IDS = {
    "goal_completion": "S114",
    "remaining_blockers": "S113",
    "deploy_preflight": "S112",
    "relation_identity": "S111",
    "coordinate": "S109",
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(read_text(path))


def rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def parse_clusters(text: str) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[0] in {"Cluster", "---"}:
            continue
        rows[cells[0]] = {"intent": cells[1], "status": cells[2], "evidence": cells[3]}
    return rows


def extract_section(text: str, heading: str) -> str:
    marker = f"## {heading}"
    start = text.find(marker)
    if start < 0:
        return ""
    next_start = text.find("\n## ", start + len(marker))
    return text[start:] if next_start < 0 else text[start:next_start]


def lower(value: str) -> str:
    return value.casefold()


def has_any(value: str, tokens: list[str]) -> bool:
    lowered = lower(value)
    return any(lower(token) in lowered for token in tokens)


def get_nested(payload: dict[str, Any], path: list[str], default: Any = None) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def build_current_facts(
    *,
    goal_completion: dict[str, Any],
    remaining_blockers: dict[str, Any],
    deploy_preflight: dict[str, Any],
    relation_identity: dict[str, Any],
    coordinate: dict[str, Any],
) -> dict[str, Any]:
    blocker_summary = remaining_blockers.get("blocker_summary", {})
    coord_freshness = coordinate.get("coordinate_freshness", {})
    coord_next_action = coordinate.get("coordinate_next_action", {})
    rust_source = coordinate.get("rust_source_evidence", {})
    relation_integrity = relation_identity.get("relation_integrity", {})
    review_validations = relation_identity.get("review_validations", {})
    return {
        "schema_version": "weekly_user_command_ledger_current_status.facts.v1",
        "source_story_ids": SOURCE_STORY_IDS,
        "goal": {
            "decision": goal_completion.get("decision"),
            "completed_count": goal_completion.get("completed_count"),
            "incomplete_count": goal_completion.get("incomplete_count"),
            "blocking_requirement_ids": goal_completion.get("blocking_requirement_ids", []),
        },
        "remaining_blockers": {
            "decision": remaining_blockers.get("decision"),
            "open_top_level_blocker_count": blocker_summary.get("open_top_level_blocker_count"),
            "open_top_level_blocker_ids": blocker_summary.get("open_top_level_blocker_ids", []),
            "exit_task_count": blocker_summary.get("exit_task_count"),
            "hard_exit_task_count": blocker_summary.get("hard_exit_task_count"),
            "final_preflight_allowed": blocker_summary.get("final_preflight_allowed"),
        },
        "deploy_preflight": {
            "decision": deploy_preflight.get("decision"),
            "required_failed_count": deploy_preflight.get("required_failed_count"),
            "hard_blocking_task_count": deploy_preflight.get("hard_blocking_task_count"),
            "failed_required_check_ids": deploy_preflight.get("failed_required_check_ids", []),
            "optional_skipped_count": deploy_preflight.get("optional_skipped_count"),
            "task_count": deploy_preflight.get("task_count"),
        },
        "relation_identity": {
            "decision": relation_identity.get("decision"),
            "blocking_reason_count": relation_identity.get("blocking_reason_count"),
            "relation_blocking_total_count": relation_integrity.get("blocking_total_count"),
            "relation_finding_count": relation_integrity.get("finding_count"),
            "approved_for_write_gate_count": review_validations.get("approved_for_write_gate_count"),
            "write_gate_candidate_count": review_validations.get("write_gate_candidate_count"),
            "next_action_task_count": relation_identity.get("next_action_task_count"),
        },
        "coordinate": {
            "decision": coordinate.get("decision"),
            "blocking_reason_count": coordinate.get("blocking_reason_count"),
            "safe_to_claim_all_latest": coord_freshness.get("safe_to_claim_all_latest"),
            "current_items_missing_geo": coord_freshness.get("current_items_missing_geo"),
            "stale_registry_active_rows": coord_freshness.get("stale_registry_active_rows"),
            "provider_accepted_count": rust_source.get("provider_accepted_count"),
            "rust_provider_accepted_count": rust_source.get("provider_accepted_count"),
            "rust_provider_review_count": rust_source.get("provider_review_count"),
            "rust_current_missing_geo_count": coord_next_action.get("rust_current_missing_geo_count"),
            "user_address_candidate": get_nested(rust_source, ["user_address_candidate", "address"]),
            "coordinate_write_allowed": coord_next_action.get("coordinate_write_allowed"),
            "next_action_task_count": coord_next_action.get("next_action_task_count"),
        },
    }


def add_finding(findings: list[dict[str, Any]], code: str, **kwargs: Any) -> None:
    item = {"code": code}
    item.update(kwargs)
    findings.append(item)


def assess_ledger_text(text: str, clusters: dict[str, dict[str, str]], facts: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    current_blockers = extract_section(text, "Current Blockers")
    next_safe = extract_section(text, "Next Safe Actions")

    required_story_tokens = ["S109", "S111", "S112", "S113"]
    for token in required_story_tokens:
        if token not in text:
            add_finding(findings, "ledger_missing_current_source_story", story_id=token)

    if CURRENT_STORY_ID not in text:
        add_finding(findings, "ledger_missing_current_reconciliation_story", story_id=CURRENT_STORY_ID)

    goal = facts["goal"]
    if goal["decision"] != "weekly_goal_completion_audit_not_complete":
        add_finding(findings, "unexpected_goal_completion_decision", decision=goal["decision"])
    if "completed `7`" not in text and "completed_count=7" not in text and "completed=7" not in text:
        add_finding(
            findings,
            "ledger_missing_current_goal_counts",
            completed_count=goal["completed_count"],
            incomplete_count=goal["incomplete_count"],
        )

    deploy_status = clusters.get("CloudRun / mini-program production path", {}).get("status", "")
    if facts["deploy_preflight"]["decision"] == "weekly_deploy_preflight_blocker_next_action_packet_blocked_report_only":
        if not has_any(deploy_status, ["blocked", "preflight blocked", "not uploadable", "not deployable"]):
            add_finding(
                findings,
                "cluster_status_conflicts_current_deploy_blocker",
                cluster="CloudRun / mini-program production path",
                ledger_status=deploy_status,
                current_decision=facts["deploy_preflight"]["decision"],
                required_failed_count=facts["deploy_preflight"]["required_failed_count"],
            )
        if has_any(deploy_status, ["deployed/uploaded", "preflight now covers", "static test"]):
            add_finding(
                findings,
                "cluster_contains_stale_deploy_green_claim",
                cluster="CloudRun / mini-program production path",
                ledger_status=deploy_status,
            )

    db_status = clusters.get("DB1 + DB2 + DB3 unification", {}).get("status", "")
    if facts["relation_identity"]["decision"] == "atlas_relation_identity_write_blocker_blocked_report_only":
        if has_any(db_status, ["guard passed", "passed", "contract locked"]) and not has_any(db_status, ["blocked", "write gate"]):
            add_finding(
                findings,
                "cluster_status_conflicts_current_relation_identity_blocker",
                cluster="DB1 + DB2 + DB3 unification",
                ledger_status=db_status,
                relation_blocking_total_count=facts["relation_identity"]["relation_blocking_total_count"],
                approved_for_write_gate_count=facts["relation_identity"]["approved_for_write_gate_count"],
            )

    relation_status = clusters.get("DJ / venue relation surface", {}).get("status", "")
    if facts["relation_identity"]["relation_blocking_total_count"]:
        if has_any(relation_status, ["passed", "guard"]) and not has_any(relation_status, ["blocked", "write gate"]):
            add_finding(
                findings,
                "cluster_status_conflicts_current_relation_surface_blocker",
                cluster="DJ / venue relation surface",
                ledger_status=relation_status,
                relation_blocking_total_count=facts["relation_identity"]["relation_blocking_total_count"],
            )

    coordinate_status = clusters.get("Address / coordinate repair", {}).get("status", "")
    if facts["coordinate"]["decision"] == "weekly_coordinate_write_blocker_blocked_report_only":
        if not has_any(coordinate_status, ["blocked", "not writable", "not fully latest"]):
            add_finding(
                findings,
                "cluster_status_conflicts_current_coordinate_blocker",
                cluster="Address / coordinate repair",
                ledger_status=coordinate_status,
            )
        if "S109" not in coordinate_status and "S109" not in clusters.get("Address / coordinate repair", {}).get("evidence", ""):
            add_finding(
                findings,
                "cluster_missing_current_coordinate_evidence",
                cluster="Address / coordinate repair",
                expected_story_id="S109",
                current_missing_geo=facts["coordinate"]["current_items_missing_geo"],
                stale_registry_active_rows=facts["coordinate"]["stale_registry_active_rows"],
            )

    if "deploy_upload_local_preflight" not in current_blockers:
        add_finding(findings, "current_blockers_missing_deploy_upload_local_preflight")
    if "address_coordinate_repair" not in current_blockers and "S109" not in current_blockers:
        add_finding(findings, "current_blockers_missing_current_coordinate_blocker")
    if "rendered_devtools_miniapp_coverage" not in current_blockers and "DevTools" not in current_blockers:
        add_finding(findings, "current_blockers_missing_devtools_rendered_blocker")
    if "relation" not in lower(current_blockers) and "S111" not in current_blockers:
        add_finding(findings, "current_blockers_missing_relation_identity_blocker")

    if "S46" in next_safe and "S109" not in next_safe:
        add_finding(
            findings,
            "next_safe_actions_still_point_to_old_s46_freeze_without_current_coordinate_story",
        )
    if "weekly:deploy-upload:preflight" in next_safe and facts["remaining_blockers"]["final_preflight_allowed"] is False:
        add_finding(
            findings,
            "next_safe_actions_may_invite_preflight_before_exit_tasks_clear",
            final_preflight_allowed=facts["remaining_blockers"]["final_preflight_allowed"],
        )

    return findings


def build_cluster_status_rows(clusters: dict[str, dict[str, str]], facts: dict[str, Any]) -> list[dict[str, Any]]:
    current_by_cluster: dict[str, dict[str, Any]] = {
        "CloudRun / mini-program production path": {
            "current_status": "blocked_pending_deploy_upload_local_preflight",
            "evidence": facts["deploy_preflight"],
        },
        "DB1 + DB2 + DB3 unification": {
            "current_status": "blocked_pending_relation_identity_write_gate",
            "evidence": facts["relation_identity"],
        },
        "DJ / venue relation surface": {
            "current_status": "blocked_pending_relation_identity_write_gate",
            "evidence": facts["relation_identity"],
        },
        "Address / coordinate repair": {
            "current_status": "blocked_pending_provider_accepted_current_coordinate",
            "evidence": facts["coordinate"],
        },
        "OpenClaw skill / self-optimization": {
            "current_status": "frozen_until_pipeline_auth_and_scheduler_are_repaired",
            "evidence": {"openclaw_pipeline_run_allowed": False},
        },
        "DJ Interview": {
            "current_status": "local_mvp_done_not_publicly_promoted",
            "evidence": {"promotion_requires_review": True},
        },
        "Week/month mobile preview": {
            "current_status": "local_done_not_final_uploaded",
            "evidence": {"deploy_upload_blocked": True},
        },
        "Mixtape / listen feature": {
            "current_status": "link_only_copyright_gate_done_not_direct_media_hosting",
            "evidence": {"direct_media_hosting_allowed": False},
        },
        "Runtime maintenance / memory": {
            "current_status": "historical_done_no_current_restart_performed",
            "evidence": {"service_restart": False},
        },
        "Anti-commercial product constitution": {
            "current_status": "done_product_boundary_preserved",
            "evidence": {"commercial_ranking_ads_allowed": False},
        },
    }
    rows: list[dict[str, Any]] = []
    for cluster, row in clusters.items():
        current = current_by_cluster.get(
            cluster,
            {"current_status": "unchanged_from_ledger_or_not_reaudited_in_s114", "evidence": {}},
        )
        rows.append(
            {
                "cluster": cluster,
                "ledger_status": row.get("status", ""),
                "current_status": current["current_status"],
                "current_evidence": current["evidence"],
            }
        )
    return rows


def build_next_action_tasks(facts: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "task_id": "ledger_current_status:update_historical_command_ledger_snapshot",
            "requirement_id": "command_ledger_current_status",
            "status": "ready_report_only",
            "hard_blocking": False,
            "detail": {
                "reason": "historical ledger predates S109/S111/S112/S113/S114 current status",
                "write_target": "report_or_docs_only",
            },
        },
        {
            "task_id": "ledger_current_status:coordinate_exit_tasks_still_blocking",
            "requirement_id": "address_coordinate_repair",
            "status": "blocked_pending_provider_accepted_current_coordinate",
            "hard_blocking": True,
            "detail": facts["coordinate"],
        },
        {
            "task_id": "ledger_current_status:relation_identity_write_gate_still_blocking",
            "requirement_id": "db1_db2_db3_unification",
            "status": "blocked_pending_source_backed_identity_dispositions",
            "hard_blocking": True,
            "detail": facts["relation_identity"],
        },
        {
            "task_id": "ledger_current_status:deploy_preflight_still_blocking",
            "requirement_id": "deploy_upload_local_preflight",
            "status": "blocked_pending_coordinate_and_relation_exit_tasks",
            "hard_blocking": True,
            "detail": facts["deploy_preflight"],
        },
    ]


def build_report(
    *,
    ledger_path: Path,
    goal_completion_path: Path,
    remaining_blockers_path: Path,
    deploy_preflight_path: Path,
    relation_identity_path: Path,
    coordinate_path: Path,
) -> dict[str, Any]:
    ledger_text = read_text(ledger_path)
    clusters = parse_clusters(ledger_text)
    goal_completion = read_json(goal_completion_path)
    remaining_blockers = read_json(remaining_blockers_path)
    deploy_preflight = read_json(deploy_preflight_path)
    relation_identity = read_json(relation_identity_path)
    coordinate = read_json(coordinate_path)
    facts = build_current_facts(
        goal_completion=goal_completion,
        remaining_blockers=remaining_blockers,
        deploy_preflight=deploy_preflight,
        relation_identity=relation_identity,
        coordinate=coordinate,
    )
    findings = assess_ledger_text(ledger_text, clusters, facts)
    stale_claim_count = len(findings)
    decision = (
        "weekly_user_command_ledger_current_status_current_report_only"
        if stale_claim_count == 0
        else "weekly_user_command_ledger_current_status_stale_report_only"
    )
    return {
        "schema_version": "weekly_user_command_ledger_current_status.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "decision": decision,
        "current_story_id": CURRENT_STORY_ID,
        "source_inputs": {
            "ledger": rel_path(ledger_path),
            "goal_completion": rel_path(goal_completion_path),
            "remaining_blockers": rel_path(remaining_blockers_path),
            "deploy_preflight": rel_path(deploy_preflight_path),
            "relation_identity": rel_path(relation_identity_path),
            "coordinate": rel_path(coordinate_path),
        },
        "cluster_count": len(clusters),
        "stale_claim_count": stale_claim_count,
        "finding_count": stale_claim_count,
        "current_facts": facts,
        "cluster_status_rows": build_cluster_status_rows(clusters, facts),
        "findings": findings,
        "next_action_tasks": build_next_action_tasks(facts),
        "hard_blocking_task_count": 3,
        "safety": {
            "report_only": True,
            "openclaw_pipeline_run": False,
            "weekly_pipeline_run": False,
            "provider_or_llm_call": False,
            "devtools_launched": False,
            "deploy_upload_review": False,
            "database_mutation": False,
            "coordinate_write": False,
            "release_rebuild": False,
            "service_restart": False,
            "secret_read": False,
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
    facts = report["current_facts"]
    lines = [
        "# Weekly User Command Ledger Current Status",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Current story: `{report['current_story_id']}`",
        f"- Historical ledger: `{report['source_inputs']['ledger']}`",
        f"- Cluster count: `{report['cluster_count']}`",
        f"- Stale claim / missing-current-evidence findings: `{report['stale_claim_count']}`",
        "",
        "## Current SSOT Readback",
        "",
        f"- Goal completion: `{facts['goal']['decision']}`; completed `{facts['goal']['completed_count']}`, incomplete `{facts['goal']['incomplete_count']}`.",
        f"- Remaining blockers: `{facts['remaining_blockers']['decision']}`; open top-level blockers `{facts['remaining_blockers']['open_top_level_blocker_count']}`, exit tasks `{facts['remaining_blockers']['exit_task_count']}`, hard exit tasks `{facts['remaining_blockers']['hard_exit_task_count']}`.",
        f"- Deploy/upload preflight: `{facts['deploy_preflight']['decision']}`; required failed `{facts['deploy_preflight']['required_failed_count']}`, hard blocking tasks `{facts['deploy_preflight']['hard_blocking_task_count']}`.",
        f"- Relation identity/write gate: `{facts['relation_identity']['decision']}`; relation blockers `{facts['relation_identity']['relation_blocking_total_count']}`, approved write-gate rows `{facts['relation_identity']['approved_for_write_gate_count']}`.",
        f"- Coordinate write gate: `{facts['coordinate']['decision']}`; current missing geo `{facts['coordinate']['current_items_missing_geo']}`, stale registry rows `{facts['coordinate']['stale_registry_active_rows']}`, Rust provider accepted `{facts['coordinate']['rust_provider_accepted_count']}`.",
        "",
        "## Cluster Status Reconciliation",
        "",
        "| Cluster | Historical Ledger Status | S114 Current Status |",
        "| --- | --- | --- |",
    ]
    for row in report["cluster_status_rows"]:
        ledger_status = row["ledger_status"].replace("|", "\\|")
        current_status = row["current_status"].replace("|", "\\|")
        lines.append(f"| {row['cluster']} | {ledger_status} | `{current_status}` |")

    lines.extend(["", "## Findings", ""])
    if not report["findings"]:
        lines.append("No stale-current-status findings.")
    else:
        for finding in report["findings"]:
            lines.append(f"- `{finding['code']}`: `{json.dumps(finding, ensure_ascii=False, sort_keys=True)}`")

    lines.extend(["", "## Next Safe Actions", ""])
    for task in report["next_action_tasks"]:
        lines.append(
            f"- `{task['task_id']}`: `{task['status']}`; hard_blocking=`{task['hard_blocking']}`"
        )

    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This reconciliation is report-only. It did not run OpenClaw or weekly pipelines, call map providers or LLMs, launch DevTools, deploy, upload, submit review, read secrets, write coordinates, mutate DB/graph/vector state, rebuild releases, restart services, or scan broad disks.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(report: dict[str, Any], out_dir: Path, scorecard_path: Path | None) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_user_command_ledger_current_status.json"
    md_path = out_dir / "weekly_user_command_ledger_current_status.md"
    tasks_path = out_dir / "weekly_user_command_ledger_current_status_tasks.jsonl"
    markdown = render_markdown(report)
    write_json(json_path, report)
    md_path.write_text(markdown, encoding="utf-8")
    write_jsonl(tasks_path, report["next_action_tasks"])
    paths = {"json": str(json_path), "markdown": str(md_path), "tasks": str(tasks_path)}
    if scorecard_path is not None:
        scorecard_path.parent.mkdir(parents=True, exist_ok=True)
        scorecard_path.write_text(markdown, encoding="utf-8")
        paths["scorecard"] = str(scorecard_path)
    return paths


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--goal-completion", type=Path, default=DEFAULT_GOAL_COMPLETION)
    parser.add_argument("--remaining-blockers", type=Path, default=DEFAULT_REMAINING_BLOCKERS)
    parser.add_argument("--deploy-preflight", type=Path, default=DEFAULT_DEPLOY_PREFLIGHT)
    parser.add_argument("--relation-identity", type=Path, default=DEFAULT_RELATION_IDENTITY)
    parser.add_argument("--coordinate", type=Path, default=DEFAULT_COORDINATE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--no-scorecard", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_report(
        ledger_path=args.ledger,
        goal_completion_path=args.goal_completion,
        remaining_blockers_path=args.remaining_blockers,
        deploy_preflight_path=args.deploy_preflight,
        relation_identity_path=args.relation_identity,
        coordinate_path=args.coordinate,
    )
    paths = write_reports(report, args.out_dir, None if args.no_scorecard else args.scorecard)
    if args.json_only:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "decision": report["decision"],
                    "current_story_id": report["current_story_id"],
                    "stale_claim_count": report["stale_claim_count"],
                    "hard_blocking_task_count": report["hard_blocking_task_count"],
                    "json": paths["json"],
                    "markdown": paths["markdown"],
                    "tasks": paths["tasks"],
                    "scorecard": paths.get("scorecard"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
