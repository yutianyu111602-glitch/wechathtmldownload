#!/usr/bin/env python3
"""Build the final Stage7 full-pipeline readiness gate.

This is a report-only fail-fast gate. It reads the PRD longrun scoreboard and
decides whether the full pipeline may start. It never starts the pipeline and
never writes production/vector/graph/DB state.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_PRD_STATUS = Path("reports/prd_longrun_status_20260515/prd_longrun_status.json")
DEFAULT_OUT_DIR = Path("reports/final_full_pipeline_readiness_20260515")
SCHEMA_VERSION = "stage7_final_full_pipeline_readiness.v1"


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


def is_blocked_status(status: str) -> bool:
    return status.startswith("blocked") or "blocked" in status


def add_unique(items: list[str], item: str) -> None:
    if item and item not in items:
        items.append(item)


def required_unblocks_from_blockers(blocker_rows: list[dict[str, Any]]) -> list[str]:
    required: list[str] = []
    for row in blocker_rows:
        for blocker in row.get("blockers") or []:
            text = str(blocker or "").casefold()
            if "dajiala_api_key" in text or "jzl_api_key" in text:
                add_unique(
                    required,
                    "Inject DAJIALA_API_KEY/JZL_API_KEY into the runtime without writing it to files, then run the bounded paid Dajiala wave gate.",
                )
            if "unknown_time_business_acceptance" in text or "unknown publish_time" in text:
                add_unique(
                    required,
                    "Resolve unknown publish_time business acceptance with accepted_by, accepted_at, and user-visible policy before production publish.",
                )
            if "production_publish" in text or "production_sqlite" in text or "consumer production publish" in text:
                add_unique(
                    required,
                    "Lift production publish and production SQLite bans only through a separate production gate with rollback owner.",
                )
            if "production graph" in text or "prd-07 graph" in text:
                add_unique(
                    required,
                    "Resolve PRD-07 graph promotion policy or explicitly keep the consumer on staging/read-only graph labels.",
                )
            if "neo4j staging write" in text or "neo4j_write" in text or "confirm token" in text:
                add_unique(
                    required,
                    "Run separate Neo4j staging write/verify gates for accepted identity and OCR rows before graph use.",
                )
            if "embedding_gate" in text:
                add_unique(
                    required,
                    "Configure and verify the embedding execution gate before poster vector materialization.",
                )
            if "qdrant_write" in text or "qdrant_alias" in text or "poster target collection" in text or "poster current alias" in text:
                add_unique(
                    required,
                    "Run the Qdrant write/alias canary after embeddings are materialized.",
                )
            if "cloud mem0" in text:
                add_unique(
                    required,
                    "Keep mem0 local-only or remove the cloud mem0 dependency before enabling personalization.",
                )
            elif "mem0" in text:
                add_unique(
                    required,
                    "Enable and verify the mem0 personalization path, or keep mem0 weight at 0 and mark the lane report-only.",
                )
            if "weekly publish path" in text:
                add_unique(
                    required,
                    "Resolve weekly publish production readiness or keep the weekly recommendation/exporter path report-only.",
                )
            if "cloudrun" in text or "cloudbase" in text or "production endpoint" in text:
                add_unique(
                    required,
                    "Configure the production CloudRun/CloudBase endpoint and post-deploy smoke target before deploy.",
                )
            if "ocr entity merge plan requires review" in text:
                add_unique(required, "Review the OCR entity merge plan before any Neo4j OCR staging apply.")
    if blocker_rows and not required:
        required.append("Clear all remaining PRD blockers listed in blocked_prd_details.")
    return required


def build_readiness(prd_status: dict[str, Any]) -> dict[str, Any]:
    prds = prd_status.get("prds") or []
    blocked = [prd for prd in prds if is_blocked_status(str(prd.get("status") or ""))]
    status_counts = Counter(str(prd.get("status") or "unknown") for prd in prds)
    non_production_ready_prds = [prd for prd in prds if not prd.get("production_ready")]
    blocker_rows = [
        {
            "id": prd.get("id"),
            "title": prd.get("title"),
            "status": prd.get("status"),
            "blockers": prd.get("blockers") or [],
            "next_safe_action": prd.get("next_safe_action"),
        }
        for prd in blocked
    ]
    critical_blockers = []
    for prd in blocked:
        prd_id = str(prd.get("id") or "")
        for blocker in prd.get("blockers") or []:
            critical_blockers.append({"prd": prd_id, "blocker": blocker})

    full_pipeline_run_allowed = not blocked and bool(prd_status.get("production_ready"))

    decision = "full_pipeline_ready" if full_pipeline_run_allowed else "full_pipeline_blocked_fail_fast_ready"
    required_unblocks = [] if full_pipeline_run_allowed else required_unblocks_from_blockers(blocker_rows)
    unsafe_actions_blocked = (
        [
            "do_not_bypass_existing_runbook_gates",
            "do_not_run_additional_paid_dajiala_waves_without_new_packet",
            "do_not_skip_rollback_owner_checks",
            "do_not_perform_destructive_data_cleanup",
        ]
        if full_pipeline_run_allowed
        else [
            "do_not_start_full_mutating_pipeline",
            "do_not_run_additional_paid_dajiala_waves_without_new_packet",
            "do_not_publish_production_consumer",
            "do_not_apply_production_graph_labels",
            "do_not_write_qdrant_poster_or_promote_aliases",
            "do_not_write_mem0",
        ]
    )
    safety = (
        [
            "existing_runbook_gates_required",
            "rollback_plan_required",
            "no_additional_paid_wave_without_new_packet",
            "no_destructive_cleanup",
        ]
        if full_pipeline_run_allowed
        else [
            "reports_only",
            "no_pipeline_start",
            "no_additional_paid_api",
            "no_graph_vector_db_write",
            "no_production_publish",
            "no_d_scan",
            "no_mem0_write",
        ]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": decision,
        "full_pipeline_run_allowed": full_pipeline_run_allowed,
        "report_only_pipeline_allowed": True,
        "production_ready": bool(prd_status.get("production_ready")),
        "total_prds": len(prds),
        "blocked_prd_count": len(blocked),
        "blocked_prds": [prd.get("id") for prd in blocked],
        "non_production_ready_prds": [prd.get("id") for prd in non_production_ready_prds],
        "status_counts": dict(status_counts),
        "critical_blockers": critical_blockers,
        "blocked_prd_details": blocker_rows,
        "global_blockers": prd_status.get("global_blockers") or [],
        "known_limitations": prd_status.get("known_limitations") or [],
        "release_decision": prd_status.get("release_decision"),
        "release_ready_gates": prd_status.get("release_ready_gates") or {},
        "unsafe_actions_blocked": unsafe_actions_blocked,
        "allowed_next_actions": (
            ["start_full_pipeline_with_existing_runbook_gates"]
            if full_pipeline_run_allowed
            else [
                "run report-only monitoring and readiness refreshes",
                "resume full pipeline only after all critical blockers are cleared",
                "keep local services healthy for future gated reruns",
            ]
        ),
        "required_unblocks": required_unblocks,
        "safety": safety,
        "writes": "gated_pipeline_allowed" if full_pipeline_run_allowed else "reports_only",
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Final Full-Pipeline Readiness",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- full_pipeline_run_allowed: `{report['full_pipeline_run_allowed']}`",
        f"- report_only_pipeline_allowed: `{report['report_only_pipeline_allowed']}`",
        f"- release_decision: `{report.get('release_decision')}`",
        f"- production_ready: `{report['production_ready']}`",
        f"- total_prds: `{report['total_prds']}`",
        f"- blocked_prd_count: `{report['blocked_prd_count']}`",
        "",
        "## Blocked PRDs",
        "",
    ]
    if report["blocked_prds"]:
        for prd_id in report["blocked_prds"]:
            lines.append(f"- `{prd_id}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Required Unblocks", ""])
    if report["required_unblocks"]:
        for item in report["required_unblocks"]:
            lines.append(f"- {item}")
    else:
        lines.append("- none")
    lines.extend(["", "## Release Ready Gates", ""])
    for key, value in sorted((report.get("release_ready_gates") or {}).items()):
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Known Limitations", ""])
    if report.get("known_limitations"):
        for item in report["known_limitations"]:
            lines.append(f"- {item}")
    else:
        lines.append("- none")
    lines.extend(["", "## Unsafe Actions Blocked", ""])
    for item in report["unsafe_actions_blocked"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Safety", ""])
    for item in report["safety"]:
        lines.append(f"- {item}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    report = build_readiness(read_json(args.prd_status))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "final_full_pipeline_readiness.json", report)
    write_markdown(args.out_dir / "final_full_pipeline_readiness.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "full_pipeline_run_allowed": report["full_pipeline_run_allowed"],
                "blocked_prd_count": report["blocked_prd_count"],
                "report": str(args.out_dir / "final_full_pipeline_readiness.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] or args.report_only_exit_zero else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prd-status", type=Path, default=DEFAULT_PRD_STATUS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
