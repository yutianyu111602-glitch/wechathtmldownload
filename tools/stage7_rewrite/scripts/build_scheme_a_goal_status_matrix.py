#!/usr/bin/env python3
"""Build a report-only Scheme A goal status matrix.

The matrix keeps the user's broad objective visible while individual lanes
advance at different speeds. It reads existing local evidence only and never
starts Docker, workers, network fetches, DB writers, projections, or release
actions.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
LONGRUN_ROOT = REPO_ROOT / "docs" / "longrun" / "atlas-route-external-db-20260531"
DEFAULT_PRD = LONGRUN_ROOT / "05-next-phase-prd.json"
DEFAULT_WAKE_STATE = LONGRUN_ROOT / "controller-wake-state.json"
DEFAULT_OPENCLAW_RUNTIME = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "openclaw_l1_l6_container_dry_run_runtime_20260602_220147"
    / "openclaw_l1_l6_container_dry_run_runtime_summary.json"
)
DEFAULT_DB3_INTAKE = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_relation_identity_s232d3b6_source_index_provider_catalog_intake_queue_20260602"
    / "atlas_relation_identity_s232d3b6_source_index_provider_catalog_intake_queue.json"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "scheme_a_goal_status_matrix_20260602"
)
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_SCHEME_A_GOAL_STATUS_MATRIX_20260602.md"
SCHEMA_VERSION = "scheme_a_goal_status_matrix.v1"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def rel(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def stories_by_id(prd: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(story.get("id")): story
        for story in prd.get("stories", [])
        if isinstance(story, dict) and story.get("id")
    }


def story_passes(stories: dict[str, dict[str, Any]], story_id: str) -> bool:
    return stories.get(story_id, {}).get("passes") is True


def story_status(stories: dict[str, dict[str, Any]], story_id: str) -> str:
    story = stories.get(story_id, {})
    if story.get("passes") is True:
        return "completed_or_report_only_passed"
    if story.get("passes") is False:
        return "open_or_blocked"
    return str(story.get("status") or "unknown")


def lane(
    lane_id: str,
    title: str,
    status: str,
    evidence: list[str],
    next_entry: str,
    *,
    requirements: list[str] | None = None,
    blockers: list[str] | None = None,
    execution_allowed_now: bool = False,
    db_write_allowed_now: bool = False,
    projection_allowed_now: bool = False,
    release_allowed_now: bool = False,
) -> dict[str, Any]:
    return {
        "lane_id": lane_id,
        "title": title,
        "status": status,
        "requirements": requirements or [],
        "evidence": evidence,
        "blockers_or_gaps": blockers or [],
        "next_entry": next_entry,
        "execution_allowed_now": execution_allowed_now,
        "db_write_allowed_now": db_write_allowed_now,
        "db2_projection_allowed_now": projection_allowed_now,
        "deploy_upload_release_allowed_now": release_allowed_now,
    }


def build_matrix(
    repo_root: Path,
    prd_path: Path,
    wake_state_path: Path,
    openclaw_runtime_path: Path,
    db3_intake_path: Path,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    prd_path = prd_path if prd_path.is_absolute() else repo_root / prd_path
    wake_state_path = wake_state_path if wake_state_path.is_absolute() else repo_root / wake_state_path
    openclaw_runtime_path = openclaw_runtime_path if openclaw_runtime_path.is_absolute() else repo_root / openclaw_runtime_path
    db3_intake_path = db3_intake_path if db3_intake_path.is_absolute() else repo_root / db3_intake_path

    prd = load_json(prd_path)
    wake_state = load_json(wake_state_path)
    openclaw_runtime = load_json(openclaw_runtime_path)
    db3_intake = load_json(db3_intake_path)
    stories = stories_by_id(prd)

    db3_blockers = []
    if db3_intake.get("compliant_catalog_row_count", 0) == 0:
        db3_blockers.append("compliant_catalog_input_missing")
    if not db3_intake.get("catalog_verification_release_created", False):
        db3_blockers.append("catalog_verification_release_missing")
    if not wake_state.get("current_phase", "").startswith("s232d3b6"):
        db3_blockers.append("wake_state_not_on_s232d3b6")

    openclaw_blockers = []
    if openclaw_runtime.get("l1_l6_complete") is not True:
        openclaw_blockers.append("l1_l6_runtime_dry_run_not_complete")
    if openclaw_runtime.get("l7_report_exists") is not False:
        openclaw_blockers.append("l7_deploy_upload_boundary_not_excluded")
    if openclaw_runtime.get("db3_s232d3b6_unlocks") is not False:
        openclaw_blockers.append("openclaw_runtime_misclassified_as_db3_unlock")

    lanes = [
        lane(
            "three_db_unification",
            "DB1/DB2/DB3 unification and performance gate",
            story_status(stories, "S121"),
            [
                "docs/longrun/atlas-route-external-db-20260531/05-next-phase-prd.json#S121",
                rel(db3_intake_path, repo_root),
            ],
            "Wait for compliant catalog/source descriptor input before DB3 write or DB2 projection.",
            requirements=["read-only DB audit", "mapping gate before DB2/DB3 promotion", "DB lock gate for writes"],
            blockers=db3_blockers,
        ),
        lane(
            "external_link_longrun",
            "Restart external-link crawl with locks, cache, DB2 weapons, and public-safe evidence",
            "report_local_canaries_passed_but_projection_blocked"
            if all(story_passes(stories, sid) for sid in ["S117", "S118", "S119", "S124", "S125"])
            else "open_or_unverified",
            [
                "docs/longrun/atlas-route-external-db-20260531/05-next-phase-prd.json#S117-S125",
                rel(openclaw_runtime_path, repo_root),
            ],
            "Use DB2/weapons consumer lane only after controller release; do not execute it from DB3 lane.",
            requirements=["file lock/cache runner", "raw-local cache", "single writer gates", "no-cookie evidence first"],
            blockers=["DB2 projection unreleased", "S130 evidence repair still open for external-link mapping"],
        ),
        lane(
            "mini_program_external_links",
            "Mini-program frontend/backend high-confidence outlink display",
            story_status(stories, "S120"),
            ["docs/longrun/atlas-route-external-db-20260531/05-next-phase-prd.json#S120"],
            "Keep display disabled for unresolved mapping/projection rows; rendered DevTools coverage still needed.",
            requirements=["Instagram/mixtape/radio/video links", "jump to original source", "no embedded media hosting"],
            blockers=["S126 rendered DevTools coverage blocker remains open", "no upload/review/release gate"],
        ),
        lane(
            "openclaw_incremental_pipeline",
            "OpenClaw download, preprocessing, no-quota DeepSeek, and L1-L6 Docker dry-run",
            "l1_l6_runtime_dry_run_passed_report_local"
            if openclaw_runtime.get("decision") == "openclaw_l1_l6_container_dry_run_runtime_passed_report_local_no_execution"
            else "open_or_unverified",
            [rel(openclaw_runtime_path, repo_root)],
            "Next runtime step must be controller-released and stay outside DB3 unless it produces compliant catalog input.",
            requirements=["Docker layered profiles", "direct DeepSeek no-quota route", "L1-L6 report-local runtime dry-run"],
            blockers=openclaw_blockers,
        ),
        lane(
            "auth_cookie_token_control",
            "Docker exporter login, API key, QR/cookie handling, and redacted runtime sync",
            story_status(stories, "S123"),
            ["docs/longrun/atlas-route-external-db-20260531/05-next-phase-prd.json#S123"],
            "Use dedicated auth lane only; never print cookie/token/API key values.",
            requirements=["redacted auth state", "dedicated profile", "headless/no-interrupt option"],
            blockers=["exporter auth refresh remains separate from DB3 gate"],
        ),
        lane(
            "poster_lineup_label_bio",
            "Poster, lineup, music label, and DJ bio recognition hardening",
            "report_only_router_and_workbench_passed"
            if all(story_passes(stories, sid) for sid in ["S122", "S125A"])
            else "open_or_unverified",
            ["docs/longrun/atlas-route-external-db-20260531/05-next-phase-prd.json#S122", "docs/longrun/atlas-route-external-db-20260531/05-next-phase-prd.json#S125A"],
            "Future execution should route image/OCR through bounded multimodal lanes and keep label/org/DJ-person separation.",
            requirements=["poster OCR", "lineup preservation", "label/person separation", "DJ bio source-backed evidence"],
            blockers=["model calls not executed by report-only routers", "DB projection still gated"],
        ),
        lane(
            "automation_and_threading",
            "Five-minute wake patrol, thread coordination, and no-subagent execution system",
            "controller_wake_state_active"
            if wake_state.get("current_phase") == "s232d3b6_consumers_closed_waiting_compliant_catalog_input_or_explicit_next_release"
            else "open_or_unverified",
            [rel(wake_state_path, repo_root)],
            "Wake patrol should read controller-wake-state, check next_valid_inputs, and stop if no DB3 release/input exists.",
            requirements=["record previous round", "overall goal", "current slice", "remaining blockers", "single-writer control"],
            blockers=["DB/crawler work must use workers/queues, not Codex subagent fan-out"],
        ),
        lane(
            "goldmine_release",
            "Local goldmine/source archive release into useful evidence",
            "partial_evidence_recovery_done_but_not_complete",
            [
                "tools/stage7_rewrite/reports/atlas_relation_source_archive_replay_s192_20260602/atlas_relation_source_archive_replay_s192.json",
                "docs/longrun/atlas-route-external-db-20260531/05-next-phase-prd.json#S191-S193",
            ],
            "Only exact archive-path or existing report-local evidence may be used; no broad D-drive scan.",
            requirements=["bounded local archive evidence", "no raw private path output", "no unbounded D-drive scan"],
            blockers=["first5 DB3 catalog still has no compliant public provider catalog input"],
        ),
    ]

    incomplete_lanes = [item["lane_id"] for item in lanes if item["blockers_or_gaps"] or "open" in item["status"]]
    next_valid_inputs = wake_state.get("next_valid_inputs", [])
    failed_checks: list[dict[str, Any]] = []
    if db3_intake.get("db_write_executed") is True:
        failed_checks.append({"check_id": "db3_intake_must_not_execute_db_write"})
    if openclaw_runtime.get("db3_s232d3b6_unlocks") is not False:
        failed_checks.append({"check_id": "openclaw_runtime_must_not_unlock_db3"})
    if openclaw_runtime.get("raw_url_private_path_secret_leak_count", 0) != 0:
        failed_checks.append({"check_id": "openclaw_runtime_leak_count_must_be_zero"})

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "scheme_a_goal_status_matrix_active_not_complete_report_only",
        "mode": "report_only_no_docker_no_worker_no_network_no_db_no_projection_no_release",
        "objective_scope_preserved": True,
        "goal_complete": False,
        "current_db3_phase": wake_state.get("current_phase"),
        "current_story_id": wake_state.get("current_story_id", "S232D-3B6"),
        "next_valid_inputs": next_valid_inputs,
        "lane_count": len(lanes),
        "incomplete_or_blocked_lane_count": len(incomplete_lanes),
        "incomplete_or_blocked_lanes": incomplete_lanes,
        "lanes": lanes,
        "execution_flags": {
            "docker_started_by_this_matrix": False,
            "worker_started_by_this_matrix": False,
            "network_fetch_executed_by_this_matrix": False,
            "db_write_executed_by_this_matrix": False,
            "db2_projection_executed_by_this_matrix": False,
            "deploy_upload_release_executed_by_this_matrix": False,
            "credential_value_read_by_this_matrix": False,
        },
        "failed_check_count": len(failed_checks),
        "failed_checks": failed_checks,
        "raw_url_private_path_secret_leak_count": 0,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Scheme A Goal Status Matrix",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Current DB3 phase: `{report.get('current_db3_phase')}`",
        f"- Current story: `{report.get('current_story_id')}`",
        f"- Goal complete: `{str(report.get('goal_complete')).lower()}`",
        f"- Lanes: `{report['lane_count']}`; incomplete/blocking: `{report['incomplete_or_blocked_lane_count']}`",
        f"- Failed checks: `{report['failed_check_count']}`; leak count: `{report['raw_url_private_path_secret_leak_count']}`",
        "",
        "## Lanes",
        "",
    ]
    for item in report["lanes"]:
        blockers = ", ".join(item["blockers_or_gaps"]) if item["blockers_or_gaps"] else "none"
        lines.extend(
            [
                f"### {item['lane_id']}",
                f"- Status: `{item['status']}`",
                f"- Blockers/gaps: `{blockers}`",
                f"- Next entry: {item['next_entry']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Boundary",
            "",
            "This matrix is report-only. It did not start Docker, workers, network fetches, DB writes, DB2 projection, deploy/upload/release, or credential reads.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--prd", type=Path, default=DEFAULT_PRD)
    parser.add_argument("--wake-state", type=Path, default=DEFAULT_WAKE_STATE)
    parser.add_argument("--openclaw-runtime", type=Path, default=DEFAULT_OPENCLAW_RUNTIME)
    parser.add_argument("--db3-intake", type=Path, default=DEFAULT_DB3_INTAKE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    args = parser.parse_args()

    report = build_matrix(args.repo_root, args.prd, args.wake_state, args.openclaw_runtime, args.db3_intake)
    out_dir = args.out_dir
    write_json(out_dir / "scheme_a_goal_status_matrix.json", report)
    write_jsonl(out_dir / "scheme_a_goal_status_lanes.jsonl", report["lanes"])
    write_markdown(out_dir / "scheme_a_goal_status_matrix.md", report)
    write_markdown(args.scorecard, report)
    print(json.dumps({"decision": report["decision"], "out_dir": str(out_dir)}, ensure_ascii=False))
    return 0 if report["failed_check_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
