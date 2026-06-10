#!/usr/bin/env python3
"""Build the final Stage7 full-pipeline launch packet from green gates.

This is a controller packet, not a runner. It consolidates the already executed
full-pipeline gates and decides whether the current artifact set is launch-ready.
It does not publish, write SQLite, mutate graph/vector stores, call paid APIs, or
scan D:.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_FINAL_READINESS = Path("reports/final_full_pipeline_readiness_20260517_verified/final_full_pipeline_readiness.json")
DEFAULT_PRD_STATUS = Path("reports/prd_longrun_status_20260517_verified/prd_longrun_status.json")
DEFAULT_E2E_FULL = Path("reports/e2e_integration_full_20260517/e2e_integration_report.json")
DEFAULT_CONSUMER_GATE = Path("reports/consumer_production_gate_packet_20260517/consumer_production_gate_packet.json")
DEFAULT_GRAPH_VERIFY = Path("reports/graph_production_promotion_verify_20260517/promotion_report.json")
DEFAULT_LIVE_RECONCILE = Path("reports/pipeline_status_93k_live_reconcile_20260517/pipeline_status_93k_live_reconcile.json")
DEFAULT_FULLMAP_SUMMARY = Path("reports/fullmap_47k_ready_text_authok_20260517_summary/summary.json")
DEFAULT_OUT_DIR = Path("reports/full_pipeline_launch_packet_20260517")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def nested(value: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    cur: Any = value
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return default if cur is None else cur


def fullmap_complete(summary: dict[str, Any]) -> bool:
    rows = int(summary.get("rows") or summary.get("articles") or 0)
    pending_total = int(summary.get("pending_total") or summary.get("pending") or 0)
    failed_total = int(summary.get("failed_total") or summary.get("failed") or 0)
    if summary.get("schema_version") == "stage7_stable_article_jsonl_merge.v1":
        return rows > 0 and pending_total == 0 and failed_total == 0 and int(summary.get("missing_uid_rows") or 0) == 0
    return rows > 0 and pending_total == 0 and failed_total == 0 and float(summary.get("progress_pct") or 0.0) >= 100.0


def build_packet(
    *,
    final_readiness: dict[str, Any],
    prd_status: dict[str, Any],
    e2e_full: dict[str, Any],
    consumer_gate: dict[str, Any],
    graph_verify: dict[str, Any],
    live_reconcile: dict[str, Any],
    fullmap_summary: dict[str, Any],
) -> dict[str, Any]:
    gates = {
        "final_readiness_allowed": bool(final_readiness.get("full_pipeline_run_allowed")),
        "prd_status_production_ready": bool(prd_status.get("production_ready")),
        "prd_blockers_clear": not bool(prd_status.get("blocked_prds")) and not bool(prd_status.get("global_blockers")),
        "full_e2e_ok": bool(e2e_full.get("ok")),
        "consumer_hard_gates_clear": not bool(consumer_gate.get("hard_gates_remaining")),
        "consumer_deploy_allowed": bool(nested(consumer_gate, ("deploy_readiness", "deploy_allowed"))),
        "graph_production_verified": bool(graph_verify.get("ok")) and bool(nested(graph_verify, ("verification", "ok"))),
        "live_93k_green": not bool(live_reconcile.get("blockers")),
        "fullmap_complete": fullmap_complete(fullmap_summary),
    }
    blockers = [name for name, ok in gates.items() if not ok]
    decision = "full_pipeline_launch_ready" if not blockers else "full_pipeline_launch_blocked"
    return {
        "schema_version": "stage7_full_pipeline_launch_packet.v1",
        "generated_at": now_iso(),
        "ok": not blockers,
        "decision": decision,
        "launch_allowed": not blockers,
        "gates": gates,
        "blockers": blockers,
        "counts": {
            "articles": fullmap_summary.get("rows") or fullmap_summary.get("articles"),
            "release_pack_articles": nested(consumer_gate, ("publish_gate", "counts", "articles")),
            "release_pack_entities": nested(consumer_gate, ("publish_gate", "counts", "entities")),
            "release_pack_events": nested(consumer_gate, ("publish_gate", "counts", "events")),
            "graph_promoted_articles": nested(graph_verify, ("after_counts", "article", "promoted")),
            "graph_promoted_entities": nested(graph_verify, ("after_counts", "entity", "promoted")),
            "graph_promoted_events": nested(graph_verify, ("after_counts", "event", "promoted")),
        },
        "evidence": {
            "final_readiness_decision": final_readiness.get("decision"),
            "prd_status_generated_at": prd_status.get("generated_at"),
            "e2e_decision": e2e_full.get("decision"),
            "consumer_gate_decision": consumer_gate.get("decision"),
            "graph_verify_decision": graph_verify.get("decision"),
            "live_reconcile_decision": live_reconcile.get("decision"),
            "fullmap_progress_pct": fullmap_summary.get("progress_pct"),
        },
        "controller_next_actions": (
            [
                "freeze_current_release_pointer_and_gate_reports",
                "start_only_existing_runbook_gated_release_jobs",
                "do_not_start_dajiala_wave07_without_new_roi_packet",
                "keep_weekly_publish_on_recommendation_exporter_path",
            ]
            if not blockers
            else ["resolve_blockers_then_rebuild_launch_packet"]
        ),
        "safety": {
            "report_only": True,
            "production_publish_executed": False,
            "production_sqlite_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
        },
        "writes": "launch_packet_only",
    }


def write_markdown(path: Path, packet: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Full Pipeline Launch Packet",
        "",
        f"- generated_at: `{packet['generated_at']}`",
        f"- decision: `{packet['decision']}`",
        f"- launch_allowed: `{packet['launch_allowed']}`",
        "",
        "## Gates",
        "",
    ]
    for name, ok in packet["gates"].items():
        lines.append(f"- {name}: `{ok}`")
    lines.extend(["", "## Counts", ""])
    for name, value in packet["counts"].items():
        lines.append(f"- {name}: `{value}`")
    lines.extend(["", "## Blockers", ""])
    if packet["blockers"]:
        for blocker in packet["blockers"]:
            lines.append(f"- `{blocker}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Controller Next Actions", ""])
    for action in packet["controller_next_actions"]:
        lines.append(f"- `{action}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Packet only. No publish, production SQLite write, graph/vector mutation, mem0 write, paid API, or D: scan.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final-readiness", type=Path, default=DEFAULT_FINAL_READINESS)
    parser.add_argument("--prd-status", type=Path, default=DEFAULT_PRD_STATUS)
    parser.add_argument("--e2e-full", type=Path, default=DEFAULT_E2E_FULL)
    parser.add_argument("--consumer-gate", type=Path, default=DEFAULT_CONSUMER_GATE)
    parser.add_argument("--graph-verify", type=Path, default=DEFAULT_GRAPH_VERIFY)
    parser.add_argument("--live-reconcile", type=Path, default=DEFAULT_LIVE_RECONCILE)
    parser.add_argument("--fullmap-summary", type=Path, default=DEFAULT_FULLMAP_SUMMARY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    packet = build_packet(
        final_readiness=read_json(args.final_readiness),
        prd_status=read_json(args.prd_status),
        e2e_full=read_json(args.e2e_full),
        consumer_gate=read_json(args.consumer_gate),
        graph_verify=read_json(args.graph_verify),
        live_reconcile=read_json(args.live_reconcile),
        fullmap_summary=read_json(args.fullmap_summary),
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "full_pipeline_launch_packet.json", packet)
    write_markdown(args.out_dir / "full_pipeline_launch_packet.md", packet)
    print(
        json.dumps(
            {
                "ok": packet["ok"],
                "decision": packet["decision"],
                "launch_allowed": packet["launch_allowed"],
                "blockers": packet["blockers"],
                "report": str(args.out_dir / "full_pipeline_launch_packet.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if packet["ok"] else 2


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
