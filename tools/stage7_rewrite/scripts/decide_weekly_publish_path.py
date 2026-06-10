#!/usr/bin/env python3
"""Choose the safe weekly publish path from PRD-11 evidence reports.

This script is report-only. It combines local E2E, schema compatibility,
weekly_event_published canary, and time_iso trace evidence into one decision.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_E2E = Path("reports/e2e_integration_20260515/e2e_integration_report.json")
DEFAULT_SCHEMA_COMPAT = Path("reports/e2e_integration_20260515/schema_compat_report.json")
DEFAULT_EVENT_CANARY = Path("reports/weekly_event_published_canary_20260515/weekly_event_published_canary.json")
DEFAULT_TIME_TRACE = Path("reports/weekly_time_iso_gap_trace_20260515/weekly_time_iso_gap_trace.json")
DEFAULT_PUBLISH_CONFIG = Path("config/consumer_publish_gate.local.json")
DEFAULT_OUT_DIR = Path("reports/weekly_publish_path_decision_20260515")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def production_target_ready(config: dict[str, Any]) -> bool:
    target = config.get("publish_target") or {}
    return bool(target.get("cloudbase_env") or target.get("cloudrun_service") or target.get("production_endpoint"))


def production_authorized(config: dict[str, Any]) -> bool:
    authorization = config.get("production_authorization") or {}
    return bool(authorization.get("production_publish_allowed")) and bool(
        authorization.get("production_sqlite_write_allowed")
    )


def build_decision(
    e2e: dict[str, Any],
    schema: dict[str, Any],
    canary: dict[str, Any],
    trace: dict[str, Any],
    publish_config: dict[str, Any] | None = None,
    allow_production_ready: bool = False,
) -> dict[str, Any]:
    e2e_ready = bool(e2e.get("ok"))
    direct_schema_blocked = not bool(schema.get("ok"))
    canary_blocked = int(canary.get("ready_count") or 0) == 0 and int(canary.get("blocked_count") or 0) > 0
    trace_proved = bool(trace.get("ok")) and "weekly_publish_dates_came_from_separate_weekly_candidate_pipeline" in (
        trace.get("root_cause") or []
    )
    weekly_current = trace.get("weekly_current_release") or {}
    weekly_current_valid = (
        int(weekly_current.get("items_seen") or 0) > 0
        and int(weekly_current.get("items_with_iso_event_date_start") or 0) == int(weekly_current.get("items_seen") or -1)
        and int(weekly_current.get("items_with_address_full") or 0) == int(weekly_current.get("items_seen") or -1)
    )
    recommended_path = (
        "weekly_recommendation_pipeline_for_weekly_publish"
        if e2e_ready and direct_schema_blocked and canary_blocked and trace_proved and weekly_current_valid
        else "hold_publish_until_evidence_gaps_are_resolved"
    )
    blocked_paths = []
    if direct_schema_blocked or canary_blocked:
        blocked_paths.append(
            {
                "path": "stage7_consumer_release_pack_direct_to_weekly_event_published",
                "status": "blocked",
                "reasons": sorted(
                    set(
                        [
                            *(schema.get("blockers") or []),
                            *list((canary.get("blocker_counts") or {}).keys()),
                        ]
                    )
                ),
            }
        )
    config = publish_config or {}
    target_ready = production_target_ready(config)
    authorized = production_authorized(config)
    production_ready = (
        allow_production_ready
        and recommended_path == "weekly_recommendation_pipeline_for_weekly_publish"
        and weekly_current_valid
        and target_ready
        and authorized
    )
    decision = (
        "weekly_publish_path_selected_production_ready"
        if production_ready
        else
        "weekly_publish_path_selected_report_only"
        if recommended_path == "weekly_recommendation_pipeline_for_weekly_publish"
        else "weekly_publish_path_blocked"
    )
    return {
        "schema_version": "stage7_weekly_publish_path_decision.v1",
        "generated_at": now_iso(),
        "ok": recommended_path == "weekly_recommendation_pipeline_for_weekly_publish",
        "decision": decision,
        "recommended_path": recommended_path,
        "production_ready": production_ready,
        "report_only": True,
        "evidence": {
            "local_e2e_ready": e2e_ready,
            "direct_schema_blocked": direct_schema_blocked,
            "event_canary_blocked": canary_blocked,
            "time_trace_proved": trace_proved,
            "weekly_current_valid": weekly_current_valid,
            "weekly_current_items": weekly_current.get("items_seen"),
            "weekly_current_iso_dates": weekly_current.get("items_with_iso_event_date_start"),
            "event_canary_ready_count": canary.get("ready_count"),
            "event_canary_blocked_count": canary.get("blocked_count"),
            "production_target_ready": target_ready,
            "production_authorized": authorized,
            "allow_production_ready": allow_production_ready,
        },
        "blocked_paths": blocked_paths,
        "required_next_gates": [
            "Keep weekly publish sourced from weekly recommendation/exporter pipeline until Stage7 stable extracts have source-backed ISO event dates.",
            "If Stage7 consumer pack is promoted later, add an event-date normalization gate before weekly_event_published adapter.",
            "Production publish/deploy remains a separate PRD-08 gate and is not performed by this report."
            if not production_ready
            else "Weekly recommendation path is ready for PRD-08 deploy gate; this report still does not publish.",
        ],
        "writes": "reports_only",
        "safety": [
            "no production publish",
            "no production SQLite write",
            "no Qdrant or Neo4j write",
            "no paid API call",
            "no D: scan",
        ],
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Weekly Publish Path Decision",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- decision: `{report['decision']}`",
        f"- recommended_path: `{report['recommended_path']}`",
        f"- production_ready: `{report['production_ready']}`",
        "",
        "## Evidence",
        "",
    ]
    for key, value in report["evidence"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Blocked Paths", ""])
    if report["blocked_paths"]:
        for item in report["blocked_paths"]:
            lines.append(f"- `{item['path']}` status=`{item['status']}`")
            for reason in item["reasons"][:20]:
                lines.append(f"  - `{reason}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Required Next Gates", ""])
    for gate in report["required_next_gates"]:
        lines.append(f"- {gate}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Reports only.",
            "- No production publish.",
            "- No production SQLite write.",
            "- No Qdrant or Neo4j write.",
            "- No paid API call.",
            "- No D: scan.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    publish_config = read_json(args.publish_config) if args.publish_config.exists() else {}
    return build_decision(
        read_json(args.e2e_report),
        read_json(args.schema_compat_report),
        read_json(args.event_canary_report),
        read_json(args.time_trace_report),
        publish_config=publish_config,
        allow_production_ready=args.allow_production_ready,
    )


def run(args: argparse.Namespace) -> int:
    report = build_report(args)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "weekly_publish_path_decision.json", report)
    write_markdown(args.out_dir / "weekly_publish_path_decision.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "recommended_path": report["recommended_path"],
                "production_ready": report["production_ready"],
                "report": str(args.out_dir / "weekly_publish_path_decision.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] or args.report_only_exit_zero else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--e2e-report", type=Path, default=DEFAULT_E2E)
    parser.add_argument("--schema-compat-report", type=Path, default=DEFAULT_SCHEMA_COMPAT)
    parser.add_argument("--event-canary-report", type=Path, default=DEFAULT_EVENT_CANARY)
    parser.add_argument("--time-trace-report", type=Path, default=DEFAULT_TIME_TRACE)
    parser.add_argument("--publish-config", type=Path, default=DEFAULT_PUBLISH_CONFIG)
    parser.add_argument("--allow-production-ready", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
