#!/usr/bin/env python3
"""Build the final superlongrun production-state packet.

This is a report-only closure packet. It consolidates live production smoke,
final readiness, all-plans landing, and known external/manual boundaries. It
does not deploy, publish, call paid APIs, read secrets, or write databases.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "stage7_superlongrun_production_state.v1"
DEFAULT_ALL_PLANS = Path("reports/all_plans_landed_20260518/all_plans_landed.json")
DEFAULT_FINAL_READINESS = Path("reports/final_full_pipeline_readiness_20260518/final_full_pipeline_readiness.json")
DEFAULT_STAGE7_SMOKE = Path("reports/superlongrun_cloudrun_stage7_smoke_20260518/cloudrun_stage7_production_smoke.json")
DEFAULT_WEEKLY_SMOKE = Path("reports/superlongrun_cloudrun_weekly_smoke_20260518/cloudrun_weekly_production_smoke.json")
DEFAULT_MINIPROGRAM_BOUNDARY = Path(
    "reports/miniprogram_review_submission_boundary_20260518/miniprogram_review_submission_boundary.json"
)
DEFAULT_SQLITE_DECISION = Path("reports/production_sqlite_surface_decision_20260518/production_sqlite_surface_decision.json")
DEFAULT_DAJIALA_GATE = Path("reports/dajiala_roi_budget_gate_packet_20260518/dajiala_roi_budget_gate_packet.json")
DEFAULT_OUT_DIR = Path("reports/superlongrun_production_state_20260518")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def endpoint_by_name(smoke: dict[str, Any], name: str) -> dict[str, Any]:
    endpoints = smoke.get("endpoints") if isinstance(smoke.get("endpoints"), list) else []
    for item in endpoints:
        if isinstance(item, dict) and item.get("name") == name:
            return item
    return {}


def plan_state(all_plans: dict[str, Any], plan_id: str) -> str:
    for item in all_plans.get("plans") or []:
        if isinstance(item, dict) and item.get("id") == plan_id:
            return str(item.get("state") or "")
    return ""


def build_packet(
    *,
    all_plans: dict[str, Any],
    final_readiness: dict[str, Any],
    stage7_smoke: dict[str, Any],
    weekly_smoke: dict[str, Any],
    miniprogram_boundary: dict[str, Any],
    sqlite_decision: dict[str, Any],
    dajiala_gate: dict[str, Any],
) -> dict[str, Any]:
    stage7_server = stage7_smoke.get("server") if isinstance(stage7_smoke.get("server"), dict) else {}
    weekly_manifest = endpoint_by_name(weekly_smoke, "manifest")
    stage7_manifest = endpoint_by_name(stage7_smoke, "manifest")
    miniprogram_limits = (
        miniprogram_boundary.get("limits") if isinstance(miniprogram_boundary.get("limits"), dict) else {}
    )

    cloudrun_production_ready = (
        stage7_smoke.get("ok") is True
        and weekly_smoke.get("ok") is True
        and str(stage7_server.get("active_flow_ratio")) == "100"
        and str(stage7_server.get("status")).casefold() == "normal"
    )
    final_gate_ready = (
        final_readiness.get("production_ready") is True
        and final_readiness.get("full_pipeline_run_allowed") is True
        and final_readiness.get("blocked_prd_count") == 0
    )
    sqlite_noop_ok = (
        sqlite_decision.get("ok") is True
        and sqlite_decision.get("production_sqlite_execution_required_now") is False
        and sqlite_decision.get("production_sqlite_write_executed") is False
    )
    miniprogram_developer_uploaded = miniprogram_limits.get("developer_version_uploaded") is True
    miniprogram_public_released = miniprogram_limits.get("public_release_completed") is True
    dajiala_held = dajiala_gate.get("next_paid_wave_allowed") is False

    local_completion_ok = (
        cloudrun_production_ready
        and final_gate_ready
        and sqlite_noop_ok
        and miniprogram_developer_uploaded
        and plan_state(all_plans, "deep_research_handoff_library_upload_pack")
        == "handoff_and_import_pack_ready_candidate_only"
    )

    external_boundaries: list[dict[str, Any]] = []
    if not miniprogram_public_released:
        external_boundaries.append(
            {
                "id": "miniprogram_review_public_release",
                "state": "external_account_side_not_executed",
                "required_action": miniprogram_boundary.get("required_external_action"),
                "blocks_cloudrun_production_state": False,
                "must_not_claim_complete": True,
            }
        )
    if dajiala_held:
        external_boundaries.append(
            {
                "id": "dajiala_wave07",
                "state": "cost_guard_hold",
                "reason": "current ROI packet keeps next_paid_wave_allowed=false",
                "blocks_cloudrun_production_state": False,
                "must_not_spend_without_fresh_roi_gate": True,
            }
        )

    blockers: list[str] = []
    if not cloudrun_production_ready:
        blockers.append("cloudrun_production_smoke_not_ready")
    if not final_gate_ready:
        blockers.append("final_readiness_gate_not_ready")
    if not sqlite_noop_ok:
        blockers.append("production_sqlite_surface_not_resolved")
    if not miniprogram_developer_uploaded:
        blockers.append("miniprogram_developer_upload_not_verified")

    production_state_entered = not blockers and local_completion_ok
    decision = (
        "superlongrun_production_state_entered_all_local_actions_complete"
        if production_state_entered
        else "superlongrun_production_state_blocked"
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": production_state_entered,
        "decision": decision,
        "production_state_entered": production_state_entered,
        "all_local_longrun_actions_complete": local_completion_ok,
        "cloudrun": {
            "ready": cloudrun_production_ready,
            "active_version": stage7_server.get("active_version"),
            "flow_ratio": stage7_server.get("active_flow_ratio"),
            "status": stage7_server.get("status"),
            "base_url": stage7_server.get("base_url"),
            "stage7_decision": stage7_smoke.get("decision"),
            "weekly_decision": weekly_smoke.get("decision"),
        },
        "stage7_counts": stage7_manifest.get("counts") or {},
        "weekly": {
            "item_count": weekly_manifest.get("item_count"),
            "manifest_generated_at": weekly_manifest.get("generated_at"),
            "materialized_no_paid_api": (
                weekly_smoke.get("safety", {}).get("paid_api_used") is False
                if isinstance(weekly_smoke.get("safety"), dict)
                else True
            ),
        },
        "final_readiness": {
            "decision": final_readiness.get("decision"),
            "production_ready": final_readiness.get("production_ready"),
            "full_pipeline_run_allowed": final_readiness.get("full_pipeline_run_allowed"),
            "blocked_prd_count": final_readiness.get("blocked_prd_count"),
            "non_production_ready_prds": final_readiness.get("non_production_ready_prds") or [],
        },
        "resolved_non_write_surfaces": {
            "production_sqlite": sqlite_decision.get("decision"),
            "miniprogram_developer_upload_verified": miniprogram_developer_uploaded,
            "deep_research_pack": plan_state(all_plans, "deep_research_handoff_library_upload_pack"),
        },
        "external_boundaries": external_boundaries,
        "blockers": blockers,
        "not_claimed_complete": [
            item["id"] for item in external_boundaries if item.get("must_not_claim_complete")
        ],
        "safety": {
            "report_only": True,
            "cloud_deploy_executed_by_this_script": False,
            "miniprogram_review_submit_executed": False,
            "miniprogram_public_release_executed": False,
            "paid_api_used": False,
            "secret_value_read_or_printed": False,
            "production_sqlite_write_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "mem0_write_executed": False,
            "d_scan_executed": False,
        },
        "writes": "report_only_superlongrun_production_state_packet",
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Superlongrun Production State Packet",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- production_state_entered: `{report['production_state_entered']}`",
        f"- all_local_longrun_actions_complete: `{report['all_local_longrun_actions_complete']}`",
        "",
        "## CloudRun",
        "",
    ]
    for key, value in report["cloudrun"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Stage7 Counts", ""])
    for key, value in (report.get("stage7_counts") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Weekly", ""])
    for key, value in report["weekly"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Blockers", ""])
    if report["blockers"]:
        lines.extend([f"- `{item}`" for item in report["blockers"]])
    else:
        lines.append("- none")
    lines.extend(["", "## External Boundaries Not Claimed Complete", ""])
    if report["external_boundaries"]:
        for item in report["external_boundaries"]:
            lines.append(f"- `{item['id']}`: `{item['state']}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Safety", ""])
    for key, value in report["safety"].items():
        lines.append(f"- {key}: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    report = build_packet(
        all_plans=read_json(args.all_plans),
        final_readiness=read_json(args.final_readiness),
        stage7_smoke=read_json(args.stage7_smoke),
        weekly_smoke=read_json(args.weekly_smoke),
        miniprogram_boundary=read_json(args.miniprogram_boundary),
        sqlite_decision=read_json(args.sqlite_decision),
        dajiala_gate=read_json(args.dajiala_gate),
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "superlongrun_production_state.json", report)
    write_markdown(args.out_dir / "superlongrun_production_state.md", report)
    print(json.dumps({"ok": report["ok"], "decision": report["decision"], "blockers": report["blockers"]}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-plans", type=Path, default=DEFAULT_ALL_PLANS)
    parser.add_argument("--final-readiness", type=Path, default=DEFAULT_FINAL_READINESS)
    parser.add_argument("--stage7-smoke", type=Path, default=DEFAULT_STAGE7_SMOKE)
    parser.add_argument("--weekly-smoke", type=Path, default=DEFAULT_WEEKLY_SMOKE)
    parser.add_argument("--miniprogram-boundary", type=Path, default=DEFAULT_MINIPROGRAM_BOUNDARY)
    parser.add_argument("--sqlite-decision", type=Path, default=DEFAULT_SQLITE_DECISION)
    parser.add_argument("--dajiala-gate", type=Path, default=DEFAULT_DAJIALA_GATE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
