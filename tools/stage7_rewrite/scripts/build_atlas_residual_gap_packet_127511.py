#!/usr/bin/env python3
"""Build the current residual-gap packet for the 127,511 atlas base.

This is a report-only closeout helper for the China underground electronic
music atlas. It reads bounded local reports and emits a no-rerun / gated-gap
table for the current all-DeepSeek + retry21 base. It does not scan D:, call
network/paid/model providers, or write graph/vector/database state.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DEFAULT_OUT_DIR = REPORTS / "atlas_residual_gap_packet_127511_20260520"
SCHEMA_VERSION = "atlas_residual_gap_packet.v1"

PATHS = {
    "stable_summary": REPORTS
    / "stable_merge_all_deepseek_127490_plus_oldroute_retry21_20260520"
    / "stable_merge_summary.json",
    "consumer_manifest": REPORTS / "consumer_release_pack_all_deepseek_127511_20260520" / "manifest.json",
    "graph_verify": REPORTS
    / "graph_production_promotion_all_deepseek_127511_verify_20260520"
    / "promotion_report.json",
    "retry_manifest": REPORTS
    / "fullmap_old_route_dajiala_retry_internal_20260520"
    / "retry_manifest_summary.json",
    "retry_selection": REPORTS
    / "fullmap_old_route_dajiala_retry_internal_20260520"
    / "dajiala_success_selection_summary.json",
    "oldroute_filter": REPORTS
    / "fullmap_old_route_ocr_debt_filter_20260519"
    / "fullmap_old_route_ocr_debt_filter_summary.json",
    "signed_audit": REPORTS / "fullmap_old_route_dajiala_signed_audit_20260519" / "archive-audit-summary.json",
    "gap_ledger": REPORTS / "atlas_gap_ledger_refresh_20260519_0715" / "gap_ledger.json",
    "external_identity_gate": REPORTS
    / "external_identity_future_direct_proof_review_gate_47k_delta375_20260519"
    / "source_followup_review_gate_summary.json",
    "vector_smoke": REPORTS
    / "vector_collection_router_smoke_oldroute_retry21_20260520"
    / "vector_collection_router_smoke.json",
    "product_manifest": ROOT.parent.parent
    / "services"
    / "weekly_activity_cloudrun"
    / "data"
    / "stage7_atlas"
    / "package_manifest.json",
}

QDRANT_VERIFY = {
    "multilingual_baseline": REPORTS
    / "qdrant_delta_verify_oldroute_retry21_20260520"
    / "multilingual_baseline_point_verify.json",
    "snowflake_canary": REPORTS
    / "qdrant_delta_verify_oldroute_retry21_20260520"
    / "snowflake_canary_point_verify.json",
    "english_sidecar": REPORTS
    / "qdrant_delta_verify_oldroute_retry21_20260520"
    / "english_sidecar_point_verify.json",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def nested(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def gap_item(gap_ledger: dict[str, Any], gap_id: str) -> dict[str, Any]:
    for item in gap_ledger.get("gap_items") or []:
        if isinstance(item, dict) and item.get("gap_id") == gap_id:
            return item
    return {}


def build_actions(inputs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    stable = inputs["stable_summary"]
    retry_manifest = inputs["retry_manifest"]
    retry_selection = inputs["retry_selection"]
    oldroute_filter = inputs["oldroute_filter"]
    signed_audit = inputs["signed_audit"]
    gap_ledger = inputs["gap_ledger"]
    external_gate = inputs["external_identity_gate"]

    v6_p1_gap = gap_item(gap_ledger, "v6_image_bucket_visual_loss")
    source_locator_rows = int(nested(oldroute_filter, "counts", "source_locator_queue_rows", default=0) or 0)
    signed_candidates = int(signed_audit.get("total_records") or 0)
    unsigned_source_repair = max(source_locator_rows - signed_candidates, 0)

    retry_failed = int(retry_selection.get("rejected_rows") or 0)
    retry_not_retried = int(retry_manifest.get("not_retried_deleted_or_unavailable_rows") or 0)

    return [
        {
            "action_id": "current_127511_no_rerun",
            "source_id": "all_deepseek_127511_retry21_atlas_base",
            "count": int(stable.get("articles") or 0),
            "class": "no_rerun_current_base",
            "decision": "Use as the current local atlas product/graph/vector truth.",
            "gate_before_execution": [],
        },
        {
            "action_id": "all_deepseek_127490_no_rerun",
            "source_id": "all_deepseek_127490_previous_base",
            "count": int(stable.get("base_rows") or 0),
            "class": "no_rerun_previous_base",
            "decision": "Already consumed full V6 and prior DeepSeek stable rows where source/stable evidence existed.",
            "gate_before_execution": [],
        },
        {
            "action_id": "oldroute_dajiala130_no_rerun",
            "source_id": "fullmap_old_route_dajiala_success130",
            "count": int(nested(stable, "lane_counts", "fullmap_old_route_dajiala_signed_recovered", default=0) or 0),
            "class": "no_rerun_consumed_paid_repair",
            "decision": "Recovered and promoted in the 47,470 checkpoint; do not rerun.",
            "gate_before_execution": [],
        },
        {
            "action_id": "oldroute_retry21_no_rerun",
            "source_id": "fullmap_old_route_dajiala_retry21",
            "count": int(retry_selection.get("selected_rows") or 0),
            "class": "no_rerun_consumed_retry",
            "decision": "Recovered and promoted into the 127,511 base; do not rerun.",
            "gate_before_execution": [],
        },
        {
            "action_id": "p1_low_quality_ocr_review_queue",
            "source_id": "v6_p1_residual_gap_queue",
            "count": int(v6_p1_gap.get("ocr_low_quality_text_review_needed") or 0),
            "class": "review_before_flash",
            "decision": "Review low-quality OCR text before any Flash/stable merge.",
            "gate_before_execution": ["source-quality review", "dedupe against current 127,511 base"],
            "queue_path": "reports/v6_p1_existing_ocr_locator_after_second_pass_20260518/v6_p1_existing_ocr_low_quality_text_review_needed.jsonl",
        },
        {
            "action_id": "p1_ocr_empty_strategy_gate",
            "source_id": "v6_p1_residual_gap_queue",
            "count": int(v6_p1_gap.get("ocr_rerun_needed") or 0),
            "class": "blocked_until_new_ocr_or_source_strategy",
            "decision": "Do not rerun empty OCR rows until a new local OCR/source-image strategy proves nonempty text.",
            "gate_before_execution": ["new OCR/source-image strategy", "bounded canary with nonempty OCR proof"],
        },
        {
            "action_id": "oldroute_retry_failures_source_gate",
            "source_id": "fullmap_old_route_dajiala_retry_failures",
            "count": retry_failed,
            "class": "source_availability_gate",
            "decision": "Rows still failed/unavailable after retry21; do not pay again without new availability proof.",
            "gate_before_execution": ["fresh source availability proof", "no-duplicate proof", "cost cap"],
        },
        {
            "action_id": "oldroute_deleted_unavailable_hold",
            "source_id": "fullmap_old_route_deleted_unavailable_not_retried",
            "count": retry_not_retried,
            "class": "hold_deleted_or_unavailable",
            "decision": "Deleted/unavailable rows were intentionally not retried.",
            "gate_before_execution": ["new source URL or account registry evidence"],
        },
        {
            "action_id": "oldroute_unsigned_source_repair_queue",
            "source_id": "fullmap_old_route_unsigned_source_repair",
            "count": unsigned_source_repair,
            "class": "source_repair_required",
            "decision": "Requires bounded source/account-registry repair before archive, OCR, LLM, paid API, or graph/vector work.",
            "gate_before_execution": ["source registry match", "bounded free recapture canary", "paid ROI packet only if signed source exists"],
            "queue_path": "reports/fullmap_old_route_ocr_debt_filter_20260519/source_locator_or_account_registry_queue.jsonl",
        },
        {
            "action_id": "external_identity_needs_more_source",
            "source_id": "external_identity_network_media_queue",
            "count": int(external_gate.get("needs_more_source_rows") or 0),
            "class": "review_only_no_graph_edges",
            "decision": "Keep accepted graph edges at zero until direct source/profile identity text passes strict review.",
            "gate_before_execution": ["direct source/profile proof", "strict review gate", "GraphCandidatePack rebuild"],
            "supporting_counts": {
                "accepted_for_graph": int(external_gate.get("accepted_for_graph") or 0),
                "candidate_direct_text_rows": int(external_gate.get("candidate_direct_text_rows") or 0),
            },
        },
    ]


def build_report() -> dict[str, Any]:
    inputs = {name: read_json(path) for name, path in PATHS.items()}
    qdrant = {role: read_json(path) for role, path in QDRANT_VERIFY.items()}
    actions = build_actions(inputs)
    hard_gated = [row for row in actions if row.get("gate_before_execution")]
    no_rerun = [row for row in actions if str(row.get("class", "")).startswith("no_rerun")]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "atlas_residual_gap_packet_ready_for_127511_base",
        "current_base": {
            "stable_articles": inputs["stable_summary"].get("articles"),
            "consumer_entities": inputs["consumer_manifest"].get("entities"),
            "consumer_events": inputs["consumer_manifest"].get("events"),
            "graph_promotion_run_id": inputs["graph_verify"].get("promotion_run_id"),
            "graph_counts": inputs["graph_verify"].get("after_counts"),
            "product_package_decision": inputs["product_manifest"].get("decision"),
        },
        "qdrant_delta_verify": {
            role: {
                "ok": payload.get("ok"),
                "total_checked": payload.get("total_checked"),
                "total_matched": payload.get("total_matched"),
            }
            for role, payload in qdrant.items()
        },
        "actions": actions,
        "summary": {
            "action_count": len(actions),
            "no_rerun_actions": len(no_rerun),
            "gate_required_actions": len(hard_gated),
            "remaining_non_waste_gap_rows": sum(int(row.get("count") or 0) for row in hard_gated),
            "accepted_external_identity_edges": int(inputs["external_identity_gate"].get("accepted_for_graph") or 0),
        },
        "inputs": {name: str(path) for name, path in PATHS.items()},
        "safety": {
            "report_only": True,
            "d_root_scan_executed": False,
            "network_call_executed": False,
            "paid_api_used": False,
            "llm_called": False,
            "ocr_execution": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "cloudrun_publish_executed": False,
            "miniprogram_upload_executed": False,
            "used_9router": False,
            "secrets_read_or_printed": False,
        },
    }
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Atlas Residual Gap Packet - 127,511",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- stable_articles: `{report['current_base'].get('stable_articles')}`",
        f"- graph_promotion_run_id: `{report['current_base'].get('graph_promotion_run_id')}`",
        f"- product_package_decision: `{report['current_base'].get('product_package_decision')}`",
        "",
        "## Summary",
        "",
    ]
    for key, value in report["summary"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Action Table", "", "| Action | Class | Count | Decision |", "| --- | --- | ---: | --- |"])
    for row in report["actions"]:
        decision = str(row.get("decision", "")).replace("|", "\\|")
        lines.append(f"| `{row['action_id']}` | `{row['class']}` | {row.get('count', '')} | {decision} |")
    lines.extend(["", "## Gates", ""])
    for row in report["actions"]:
        gates = row.get("gate_before_execution") or []
        if not gates:
            continue
        lines.append(f"### {row['action_id']}")
        for gate in gates:
            lines.append(f"- {gate}")
        lines.append("")
    lines.extend(["## Safety", ""])
    for key, value in report["safety"].items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    report = build_report()
    out_dir = args.out_dir
    write_json(out_dir / "atlas_residual_gap_packet.json", report)
    write_text(out_dir / "atlas_residual_gap_packet.md", render_markdown(report))
    write_jsonl(out_dir / "residual_gap_actions.jsonl", report["actions"])
    print(json.dumps({"ok": True, "out_dir": str(out_dir), "decision": report["decision"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
