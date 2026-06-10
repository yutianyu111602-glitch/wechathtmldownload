#!/usr/bin/env python3
"""Build a report-only atlas gap/backfill execution packet.

This is the next step after the source-lineage packet. It turns current 47k,
93k/FULL_MAP, V6/OCR, Dajiala, external identity, and vector lineage decisions
into a no-rerun / hold / gated-backfill table. It does not scan D:, call paid
APIs, run OCR/LLM, or write graph/vector/database state.
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
DEFAULT_LINEAGE = REPORTS / "atlas_full_source_lineage_47k_93k_gap_20260519" / "atlas_full_source_lineage.json"
DEFAULT_GAP = REPORTS / "atlas_gap_ledger_refresh_20260519_0715" / "gap_ledger.json"
DEFAULT_DAJIALA_ROI = REPORTS / "dajiala_roi_budget_gate_packet_20260518" / "dajiala_roi_budget_gate_packet.json"
DEFAULT_OUT_DIR = REPORTS / "atlas_gap_backfill_execution_packet_20260519"
SCHEMA_VERSION = "atlas_gap_backfill_execution_packet.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


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


def layer_by_id(lineage: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(layer.get("source_id")): layer
        for layer in lineage.get("source_layers") or []
        if isinstance(layer, dict) and layer.get("source_id")
    }


def gap_item(gap: dict[str, Any], gap_id: str) -> dict[str, Any]:
    for item in gap.get("gap_items") or []:
        if isinstance(item, dict) and item.get("gap_id") == gap_id:
            return item
    return {}


def nested_get(data: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def count_from_layer(layers: dict[str, dict[str, Any]], source_id: str, fallback: int = 0) -> int:
    value = layers.get(source_id, {}).get("count_signal")
    try:
        return int(value)
    except Exception:
        return fallback


def build_actions(lineage: dict[str, Any], gap: dict[str, Any], roi: dict[str, Any]) -> list[dict[str, Any]]:
    layers = layer_by_id(lineage)
    gap_summary = gap.get("summary") if isinstance(gap.get("summary"), dict) else {}
    image_gap = gap_item(gap, "v6_image_bucket_visual_loss")
    fullmap_gap = gap_item(gap, "fullmap_ocr_missing_old_route")
    roi_metrics = roi.get("roi_metrics") if isinstance(roi.get("roi_metrics"), dict) else {}

    return [
        {
            "action_id": "current_47340_marker_no_rerun",
            "source_id": "current_47340_atlas_graph_marker",
            "count": count_from_layer(layers, "current_47340_atlas_graph_marker"),
            "class": "no_rerun_current_base",
            "decision": "Use as the current atlas production base; no recapture/re-extraction required for this marker.",
            "gate_before_execution": [],
        },
        {
            "action_id": "v6_p1_repair_no_rerun",
            "source_id": "v6_p1_ocr_markdown_visual_repair",
            "count": count_from_layer(layers, "v6_p1_ocr_markdown_visual_repair"),
            "class": "no_rerun_consumed_repair",
            "decision": "Already promoted strict P1 OCR/Markdown/Flash repair rows; do not rerun.",
            "gate_before_execution": [],
        },
        {
            "action_id": "paid_wave09_21_delta_no_rerun",
            "source_id": "paid_dajiala_wave09_21_delta375_repair",
            "count": count_from_layer(layers, "paid_dajiala_wave09_21_delta375_repair"),
            "class": "no_rerun_consumed_paid_delta",
            "decision": "Already consumed verified local OCR wave09-21 delta; do not start duplicate paid repair.",
            "gate_before_execution": [],
        },
        {
            "action_id": "fullmap_93k_hold_as_lineage",
            "source_id": "fullmap_93k_extraction_lineage",
            "count": count_from_layer(layers, "fullmap_93k_extraction_lineage"),
            "class": "hold_upstream_lineage",
            "decision": "Use as upstream/source evidence lineage only; not an automatic additional graph promotion.",
            "gate_before_execution": ["merge-readiness packet proving a new non-duplicate promoted slice"],
        },
        {
            "action_id": "full_v6_81417_hold_candidate",
            "source_id": "full_v6_81417_structured_candidate",
            "count": count_from_layer(layers, "full_v6_81417_structured_candidate"),
            "class": "hold_candidate_only",
            "decision": "Keep full V6 rows candidate-only; promote only smaller source-backed slices.",
            "gate_before_execution": [
                "source evidence review",
                "merge-readiness packet",
                "dry-run graph import",
                "post-promote verification",
            ],
            "supporting_counts": {
                "text_only_flash_rows": gap_summary.get("v6_image_bucket_rows_text_only_flash"),
                "p2_flash_quality_reextract_needed": image_gap.get("p2_flash_quality_reextract_needed"),
                "p3_accepted_but_event_missing_review": image_gap.get("p3_accepted_but_event_missing_review"),
            },
        },
        {
            "action_id": "p1_low_quality_ocr_review_queue",
            "source_id": "v6_p1_residual_gap_queue",
            "count": int(gap_summary.get("p1_low_quality_text_review_rows") or 0),
            "class": "review_before_flash",
            "decision": "Review low-quality OCR text rows before any Flash or graph merge.",
            "gate_before_execution": ["quality review accepts OCR text as source evidence", "dedupe against current 47,340 marker"],
            "queue_path": "reports/v6_p1_existing_ocr_locator_after_second_pass_20260518/v6_p1_existing_ocr_low_quality_text_review_needed.jsonl",
        },
        {
            "action_id": "p1_ocr_empty_strategy_gate",
            "source_id": "v6_p1_residual_gap_queue",
            "count": int(gap_summary.get("p1_remaining_local_ocr_rerun_rows") or 0),
            "class": "blocked_until_new_ocr_strategy",
            "decision": "Do not rerun empty OCR rows until a new source/image strategy exists.",
            "gate_before_execution": ["new local OCR strategy or source-image locator", "bounded canary with proof of nonempty text"],
        },
        {
            "action_id": "fullmap_old_route_ocr_missing_filter_gate",
            "source_id": "fullmap_ocr_missing_old_route",
            "count": int(fullmap_gap.get("needs_ocr_remaining") or 0),
            "class": "filter_before_paid_or_ocr",
            "decision": "Old-route OCR debt is known low-ROI; filter to source/image-backed rows before OCR or paid work.",
            "gate_before_execution": ["source/image evidence manifest", "no-duplicate proof", "bounded non-paid canary first"],
            "supporting_counts": {
                "latest_gap_ledger_remaining": fullmap_gap.get("needs_ocr_remaining"),
                "older_roi_fixed_route_missing": roi_metrics.get("fixed_route_missing"),
            },
        },
        {
            "action_id": "dajiala_remaining_paid_gate",
            "source_id": "dajiala_paid_round_inventory_and_remaining_gate",
            "count": int(roi_metrics.get("known_unconsumed_queue_rows") or 0),
            "class": "paid_blocked_until_roi_gate",
            "decision": "Do not run more paid Dajiala from inventory alone.",
            "gate_before_execution": [
                "fresh max spend cap",
                "signed-long-link-only target queue",
                "no-duplicate proof against consumed wave09-21 delta",
                "downstream consumption plan",
                "balance query only when explicitly authorized",
            ],
            "supporting_counts": {
                "latest_archive_failed": roi_metrics.get("latest_archive_failed"),
                "next_paid_wave_allowed": roi.get("next_paid_wave_allowed"),
                "hard_gates_remaining": roi.get("hard_gates_remaining"),
            },
        },
        {
            "action_id": "external_identity_no_edges_until_direct_proof",
            "source_id": "external_identity_network_media_queue",
            "count": count_from_layer(layers, "external_identity_network_media_queue"),
            "class": "no_graph_edges",
            "decision": "Keep accepted graph edges at zero until direct source/profile proof passes strict review.",
            "gate_before_execution": ["ATLAS-P3-S3 source-context decision", "direct source/profile identity proof"],
            "supporting_counts": {
                "accepted_for_graph": nested_get(layers, ("external_identity_network_media_queue", "counts", "accepted_for_graph"), 0),
                "needs_more_source_rows": nested_get(layers, ("external_identity_network_media_queue", "counts", "needs_more_source_rows")),
            },
        },
        {
            "action_id": "vector_alias_apply_stays_gated",
            "source_id": "role_isolated_vector_staging",
            "count": count_from_layer(layers, "role_isolated_vector_staging"),
            "class": "apply_gate_required",
            "decision": "Four role staging reports are present; production alias apply remains a separate explicit gate.",
            "gate_before_execution": ["ENABLE_QDRANT_ROLE_ALIAS_PROMOTE", "rollback packet", "post-apply router smoke"],
        },
    ]


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Atlas Gap Backfill Execution Packet",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        "",
        "## Action Table",
        "",
        "| Action | Class | Count | Decision |",
        "| --- | --- | ---: | --- |",
    ]
    for action in report["actions"]:
        lines.append(
            "| `{action_id}` | `{klass}` | {count} | {decision} |".format(
                action_id=action["action_id"],
                klass=action["class"],
                count=action.get("count") if action.get("count") is not None else "",
                decision=str(action.get("decision", "")).replace("|", "\\|"),
            )
        )
    lines.extend(["", "## Gates", ""])
    for action in report["actions"]:
        gates = action.get("gate_before_execution") or []
        if not gates:
            continue
        lines.append(f"### {action['action_id']}")
        for gate in gates:
            lines.append(f"- {gate}")
        lines.append("")
    lines.extend(["## Safety", ""])
    for key, value in report["safety"].items():
        lines.append(f"- `{key}`: `{value}`")
    return "\n".join(lines).rstrip() + "\n"


def build_packet(
    lineage_path: Path = DEFAULT_LINEAGE,
    gap_path: Path = DEFAULT_GAP,
    dajiala_roi_path: Path = DEFAULT_DAJIALA_ROI,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    lineage = read_json(lineage_path)
    gap = read_json(gap_path)
    roi = read_json(dajiala_roi_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    actions = build_actions(lineage, gap, roi)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "atlas_gap_backfill_execution_packet_ready_report_only",
        "inputs": {
            "lineage": str(lineage_path),
            "gap": str(gap_path),
            "dajiala_roi": str(dajiala_roi_path),
        },
        "actions": actions,
        "summary": {
            "action_count": len(actions),
            "no_rerun_count": sum(1 for action in actions if str(action.get("class", "")).startswith("no_rerun")),
            "hold_count": sum(1 for action in actions if str(action.get("class", "")).startswith("hold")),
            "gate_required_count": sum(1 for action in actions if action.get("gate_before_execution")),
            "paid_action_allowed": False,
            "production_write_allowed": False,
        },
        "safety": {
            "report_only": True,
            "d_scan_executed": False,
            "network_called": False,
            "llm_called": False,
            "ocr_execution": False,
            "paid_api_used": False,
            "qdrant_write_executed": False,
            "qdrant_alias_change_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "secrets_read_or_printed": False,
            "used_9router": False,
        },
    }
    write_json(out_dir / "gap_backfill_execution_packet.json", report)
    write_text(out_dir / "gap_backfill_execution_packet.md", render_markdown(report))
    write_jsonl(out_dir / "gap_backfill_actions.jsonl", actions)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lineage-path", type=Path, default=DEFAULT_LINEAGE)
    parser.add_argument("--gap-path", type=Path, default=DEFAULT_GAP)
    parser.add_argument("--dajiala-roi-path", type=Path, default=DEFAULT_DAJIALA_ROI)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_packet(args.lineage_path, args.gap_path, args.dajiala_roi_path, args.out_dir)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "action_count": report["summary"]["action_count"],
                "gate_required_count": report["summary"]["gate_required_count"],
                "report": str(args.out_dir / "gap_backfill_execution_packet.json"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
