#!/usr/bin/env python3
"""Build the Stage7 data completeness gap ledger from verified report artifacts.

This is a report-only reconciliation step. It does not scan D:, call paid APIs,
run OCR/LLM/vector jobs, or write graph/vector stores.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OUT_DIR = Path("reports/stage7_data_completeness_gap_ledger_20260518")
SCHEMA_VERSION = "stage7_data_completeness_gap_ledger.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    tmp.replace(path)


def count_existing(paths: dict[str, str]) -> dict[str, bool]:
    return {key: Path(value).exists() for key, value in paths.items()}


def build_gap_items(
    *,
    source_lane: dict[str, Any],
    image_loss: dict[str, Any],
    ocr_index: dict[str, Any],
    flash_summary: dict[str, Any],
    stable_summary: dict[str, Any],
    promotion: dict[str, Any],
    p1_full_flash_summary: dict[str, Any],
    p1_parse_repair_flash_summary: dict[str, Any],
    p1_parse_repair_merge: dict[str, Any],
    p1_stable_repaired_summary: dict[str, Any],
    p1_promotion_verify: dict[str, Any],
    p1_locator_after_local_ocr: dict[str, Any],
    p1_local_ocr_repair_summary: dict[str, Any],
    p1_incremental_flash_summary: dict[str, Any],
    p1_incremental_stable_summary: dict[str, Any],
    p1_incremental_promotion_verify: dict[str, Any],
    p1_second_pass_locator: dict[str, Any],
    p1_second_pass_ocr_repair_summary: dict[str, Any],
    p1_second_pass_flash_summary: dict[str, Any],
    p1_second_pass_stable_summary: dict[str, Any],
    p1_second_pass_promotion_verify: dict[str, Any],
    merged_stable_summary: dict[str, Any],
    merged_readiness_packet: dict[str, Any],
    merged_graph_promotion_verify: dict[str, Any],
    external_roots: dict[str, Any],
    crash_guard: dict[str, Any],
    p1_ocr_locator: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    source_summary = source_lane.get("summary") or {}
    priority_counts = image_loss.get("priority_counts") or {}
    v6_counts = (((source_lane.get("lanes") or [])[1] if len(source_lane.get("lanes") or []) > 1 else {}).get("counts") or {})
    fullmap_lane = ((source_lane.get("lanes") or [])[2] if len(source_lane.get("lanes") or []) > 2 else {})
    fullmap_counts = fullmap_lane.get("counts") or {}
    production_counts = fullmap_lane.get("production_graph_counts") or {}
    promoted_counts = promotion.get("after_counts") or {}
    p1_promoted_counts = p1_promotion_verify.get("after_counts") or {}
    p1_incremental_promoted_counts = p1_incremental_promotion_verify.get("after_counts") or {}
    p1_second_pass_promoted_counts = p1_second_pass_promotion_verify.get("after_counts") or {}
    merged_graph_promoted_counts = merged_graph_promotion_verify.get("after_counts") or {}
    locator_counts = (p1_ocr_locator or {}).get("counts") or {}
    strict_locator_counts = p1_locator_after_local_ocr.get("counts") or {}
    second_pass_locator_counts = p1_second_pass_locator.get("counts") or {}
    current_locator_counts = second_pass_locator_counts or strict_locator_counts or locator_counts
    p1_full_cost = p1_full_flash_summary.get("estimated_cny")
    p1_repair_cost = p1_parse_repair_flash_summary.get("estimated_cny")
    p1_incremental_cost = p1_incremental_flash_summary.get("estimated_cny")
    p1_second_pass_cost = p1_second_pass_flash_summary.get("estimated_cny")
    p1_base_total_cost = None
    if any(isinstance(value, (int, float)) for value in (p1_full_cost, p1_repair_cost)):
        p1_base_total_cost = round(float(p1_full_cost or 0) + float(p1_repair_cost or 0), 4)
    p1_total_cost = None
    if any(isinstance(value, (int, float)) for value in (p1_full_cost, p1_repair_cost, p1_incremental_cost, p1_second_pass_cost)):
        p1_total_cost = round(
            float(p1_full_cost or 0) + float(p1_repair_cost or 0) + float(p1_incremental_cost or 0) + float(p1_second_pass_cost or 0),
            4,
        )
    total_p1_promoted_article = (p1_promoted_counts.get("article") or {}).get("promoted", 0) + (
        p1_incremental_promoted_counts.get("article") or {}
    ).get("promoted", 0) + (p1_second_pass_promoted_counts.get("article") or {}).get("promoted", 0)
    total_p1_promoted_entity = (p1_promoted_counts.get("entity") or {}).get("promoted", 0) + (
        p1_incremental_promoted_counts.get("entity") or {}
    ).get("promoted", 0) + (p1_second_pass_promoted_counts.get("entity") or {}).get("promoted", 0)
    total_p1_promoted_event = (p1_promoted_counts.get("event") or {}).get("promoted", 0) + (
        p1_incremental_promoted_counts.get("event") or {}
    ).get("promoted", 0) + (p1_second_pass_promoted_counts.get("event") or {}).get("promoted", 0)

    return [
        {
            "gap_id": "current_47k_text_graph_lane",
            "status": "complete_in_production_graph",
            "article_count": source_summary.get("current_production_graph_article_count") or production_counts.get("article"),
            "entity_count": source_summary.get("current_production_graph_entity_count") or production_counts.get("entity"),
            "event_count": source_summary.get("current_production_graph_event_count") or production_counts.get("event"),
            "evidence": "reports/production_graph_source_lane_audit_20260518/source_lane_audit.json",
            "next_action": "Keep as the old 47K text graph baseline; the current expanded marker is 47K+P1 repair.",
        },
        {
            "gap_id": "merged_47k_plus_v6_p1_repair_graph_lane",
            "status": "complete_in_production_graph",
            "stable_articles": merged_stable_summary.get("articles"),
            "base_47k_rows": ((merged_readiness_packet.get("merge_summary") or {}).get("base_47k_rows")),
            "p1_repair_rows": ((merged_readiness_packet.get("merge_summary") or {}).get("p1_repair_rows")),
            "duplicate_addon_rows": merged_stable_summary.get("duplicate_addon_rows"),
            "promoted_article": (merged_graph_promoted_counts.get("article") or {}).get("promoted"),
            "promoted_entity": (merged_graph_promoted_counts.get("entity") or {}).get("promoted"),
            "promoted_event": (merged_graph_promoted_counts.get("event") or {}).get("promoted"),
            "evidence": "reports/graph_production_promotion_47k_plus_v6_p1_repair_1397_verify_20260518/promotion_report.json",
            "next_action": "Use this 46,965-article graph marker as the current text+P1 repair graph candidate; full V6 81K remains candidate-only.",
        },
        {
            "gap_id": "v6_81k_structured_baseline",
            "status": "verified_structured_candidate_not_promoted_to_current_graph",
            "processed_samples": v6_counts.get("processed_samples"),
            "scored_rows": v6_counts.get("scored_rows"),
            "accept_flash": v6_counts.get("accept_flash"),
            "pro_reextract": v6_counts.get("pro_reextract"),
            "evidence": "reports/production_graph_source_lane_audit_20260518/source_lane_audit.json",
            "next_action": "Use reports/v6_47k_merge_readiness_packet_20260518 as the 47K+P1 repair merge packet; full V6 81K remains candidate-only.",
        },
        {
            "gap_id": "v6_image_bucket_visual_loss",
            "status": "partial_repair_complete_remaining_local_ocr",
            "image_bucket_rows": (image_loss.get("counts") or {}).get("image_bucket_rows"),
            "p1_likely_visual_missing": priority_counts.get("P1_likely_visual_info_missing"),
            "p2_flash_quality_reextract_needed": priority_counts.get("P2_flash_quality_reextract_needed"),
            "p3_accepted_but_event_missing_review": priority_counts.get("P3_accepted_but_event_missing_review"),
            "p4_low_priority_rich_flash_output": priority_counts.get("P4_low_priority_rich_flash_output"),
            "existing_poster_ocr_rows": current_locator_counts.get("poster_ocr_exists", 0),
            "existing_ocr_covered_rows": current_locator_counts.get("poster_ocr_text_gt0", 0),
            "ocr_quality_accepted_rows": current_locator_counts.get("poster_ocr_quality_accepted", current_locator_counts.get("poster_ocr_text_gt0", 0)),
            "merge_ocr_markdown_flash_ready": current_locator_counts.get("merge_ocr_markdown_flash_ready", 0),
            "merge_ready_promoted_to_graph": total_p1_promoted_article,
            "remaining_local_ocr_rerun_needed": current_locator_counts.get("ocr_rerun_needed", 0),
            "ocr_rerun_needed": current_locator_counts.get("ocr_rerun_needed", 0),
            "ocr_low_quality_text_review_needed": current_locator_counts.get("ocr_low_quality_text_review_needed", 0),
            "static_frame_required": current_locator_counts.get("static_frame_required", 0),
            "recapture_or_external_locator_needed": current_locator_counts.get("recapture_or_external_locator_needed", 0),
            "evidence": "reports/v6_image_bucket_loss_audit_20260518/v6_image_bucket_loss_audit_summary.json",
            "next_action": "P1 strict repair has promoted 1,397 rows; continue with 30 OCR-empty rows and 99 low-quality OCR review rows; no blind paid recapture for P1.",
        },
        {
            "gap_id": "v6_p1_existing_ocr_markdown_repair_subgraph",
            "status": "complete_in_production_graph",
            "input_rows": locator_counts.get("merge_ocr_markdown_flash_ready", 0),
            "flash_processed_samples": p1_full_flash_summary.get("processed_samples"),
            "flash_chunks_api_ok": p1_full_flash_summary.get("api_ok_chunks"),
            "flash_chunks_parse_ok_before_repair": p1_full_flash_summary.get("parse_ok_chunks"),
            "flash_chunks_parse_ok_after_repair": p1_parse_repair_merge.get("parse_ok_chunks"),
            "flash_chunks_schema_ok_after_repair": p1_parse_repair_merge.get("schema_ok_chunks"),
            "parse_repair_rows": p1_parse_repair_merge.get("repair_rows"),
            "parse_bad_after_repair": p1_parse_repair_merge.get("bad_after_repair", []),
            "flash_estimated_cny": p1_full_cost,
            "parse_repair_estimated_cny": p1_repair_cost,
            "total_estimated_cny": p1_base_total_cost,
            "stable_articles": p1_stable_repaired_summary.get("articles"),
            "stable_chunks_parse_failed": p1_stable_repaired_summary.get("chunks_raw_parse_failed"),
            "promoted_article": (p1_promoted_counts.get("article") or {}).get("promoted"),
            "promoted_entity": (p1_promoted_counts.get("entity") or {}).get("promoted"),
            "promoted_event": (p1_promoted_counts.get("event") or {}).get("promoted"),
            "evidence": "reports/graph_production_promotion_v6_p1_ocr_markdown_flash_full1082_verify_20260518/promotion_report.json",
            "next_action": "Use this as the first P1 visual-loss repair template; do not rerun these 1,082 rows.",
        },
        {
            "gap_id": "v6_p1_local_ocr_static_frame_incremental287_repair_subgraph",
            "status": "complete_in_production_graph",
            "local_ocr_executed_rows": (p1_local_ocr_repair_summary.get("counts") or {}).get("executed_rows"),
            "local_ocr_ok_text_rows": (p1_local_ocr_repair_summary.get("counts") or {}).get("ok_text_rows"),
            "local_ocr_no_text_rows": (p1_local_ocr_repair_summary.get("counts") or {}).get("no_text_rows"),
            "local_ocr_frames_extracted": (p1_local_ocr_repair_summary.get("counts") or {}).get("frames_extracted"),
            "strict_incremental_flash_rows": p1_incremental_flash_summary.get("processed_samples"),
            "flash_chunks_parse_ok": p1_incremental_flash_summary.get("parse_ok_chunks"),
            "flash_estimated_cny": p1_incremental_cost,
            "total_p1_repair_estimated_cny": p1_total_cost,
            "stable_articles": p1_incremental_stable_summary.get("articles"),
            "stable_chunks_parse_failed": p1_incremental_stable_summary.get("chunks_raw_parse_failed"),
            "promoted_article": (p1_incremental_promoted_counts.get("article") or {}).get("promoted"),
            "promoted_entity": (p1_incremental_promoted_counts.get("entity") or {}).get("promoted"),
            "promoted_event": (p1_incremental_promoted_counts.get("event") or {}).get("promoted"),
            "evidence": "reports/graph_production_promotion_v6_p1_local_ocr_flash_incremental_287_verify_20260518/promotion_report.json",
            "next_action": "Do not rerun these rows; the later second-pass leaves 99 low-quality text rows and 30 OCR-empty rows.",
        },
        {
            "gap_id": "v6_p1_local_ocr_second_pass_incremental28_repair_subgraph",
            "status": "complete_in_production_graph",
            "local_ocr_executed_rows": (p1_second_pass_ocr_repair_summary.get("counts") or {}).get("executed_rows"),
            "local_ocr_ok_text_rows": (p1_second_pass_ocr_repair_summary.get("counts") or {}).get("ok_text_rows"),
            "local_ocr_no_text_rows": (p1_second_pass_ocr_repair_summary.get("counts") or {}).get("no_text_rows"),
            "local_ocr_frames_extracted": (p1_second_pass_ocr_repair_summary.get("counts") or {}).get("frames_extracted"),
            "strict_incremental_flash_rows": p1_second_pass_flash_summary.get("processed_samples"),
            "flash_chunks_parse_ok": p1_second_pass_flash_summary.get("parse_ok_chunks"),
            "flash_estimated_cny": p1_second_pass_cost,
            "total_p1_repair_estimated_cny": p1_total_cost,
            "stable_articles": p1_second_pass_stable_summary.get("articles"),
            "stable_chunks_parse_failed": p1_second_pass_stable_summary.get("chunks_raw_parse_failed"),
            "promoted_article": (p1_second_pass_promoted_counts.get("article") or {}).get("promoted"),
            "promoted_entity": (p1_second_pass_promoted_counts.get("entity") or {}).get("promoted"),
            "promoted_event": (p1_second_pass_promoted_counts.get("event") or {}).get("promoted"),
            "evidence": "reports/graph_production_promotion_v6_p1_local_ocr_second_pass_flash_incremental_28_verify_20260518/promotion_report.json",
            "next_action": "Do not rerun these rows; current residual P1 is 99 low-quality text review rows and 30 OCR-empty rows.",
        },
        {
            "gap_id": "paid_ocr_432_repair_subgraph",
            "status": "complete_in_production_graph",
            "ocr_ready_rows": ocr_index.get("record_count"),
            "flash_processed_samples": flash_summary.get("processed_samples"),
            "flash_chunks_parse_ok": flash_summary.get("parse_ok_chunks"),
            "flash_estimated_cny": flash_summary.get("estimated_cny"),
            "stable_articles": stable_summary.get("articles"),
            "promoted_article": (promoted_counts.get("article") or {}).get("promoted"),
            "promoted_entity": (promoted_counts.get("entity") or {}).get("promoted"),
            "promoted_event": (promoted_counts.get("event") or {}).get("promoted"),
            "evidence": "reports/graph_production_promotion_ocr_markdown_flash_full432_verify_20260518/promotion_report.json",
            "next_action": "Use as proven repair template for future validated OCR rows.",
        },
        {
            "gap_id": "external_user_roots",
            "status": "validation_only_not_ingested",
            "root_count": external_roots.get("root_count"),
            "trust_status": external_roots.get("all_trust_status"),
            "evidence": "reports/stage7_external_data_roots_validation_20260518/external_data_roots_validation_packet.json",
            "next_action": "Build bounded validation manifests; only source-identified, deduped, image-backed rows can enter OCR/Flash.",
        },
        {
            "gap_id": "native_vector_embedding_lane",
            "status": "guarded_not_blocking_text_graph",
            "runtime_guard_enabled": bool((crash_guard.get("stage7_runtime_guard") or {}).get("enabled")),
            "requires_project_virtualenv": bool((crash_guard.get("stage7_runtime_guard") or {}).get("requires_project_virtualenv")),
            "evidence": "reports/crash_dump_guard_20260518/crash_dump_guard_report.json",
            "next_action": "Do not run native vector jobs until a Python 3.11/3.12 Stage7 vector venv is explicit.",
        },
        {
            "gap_id": "fullmap_ocr_missing_old_route",
            "status": "known_low_roi_backlog_do_not_blind_pay",
            "needs_ocr_all": fullmap_counts.get("needs_ocr_all"),
            "needs_ocr_already_processed": fullmap_counts.get("needs_ocr_already_processed"),
            "needs_ocr_remaining": fullmap_counts.get("needs_ocr_remaining"),
            "evidence": "reports/production_graph_source_lane_audit_20260518/source_lane_audit.json",
            "next_action": "Only spend paid Dajiala on a newly filtered, high-ROI queue with source/image evidence.",
        },
    ]


def build_report(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    inputs = {
        "source_lane": "reports/production_graph_source_lane_audit_20260518/source_lane_audit.json",
        "image_loss": "reports/v6_image_bucket_loss_audit_20260518/v6_image_bucket_loss_audit_summary.json",
        "ocr_index": "reports/dajiala_paid_latest_verified_combined_ocr_index_20260518/ocr_file_index_summary.json",
        "flash_summary": "reports/ocr_markitdown_flash_reprocess_flash_full432_20260518/flash_run432_verified_ocr/flash_summary.json",
        "stable_summary": "reports/ocr_markdown_flash_full432_stable_extract_20260518/stable_materialize_summary.json",
        "promotion": "reports/graph_production_promotion_ocr_markdown_flash_full432_verify_20260518/promotion_report.json",
        "p1_full_flash_summary": "reports/v6_p1_ocr_markdown_flash_full1082_20260518/flash_run1082/flash_summary.json",
        "p1_parse_repair_flash_summary": "reports/v6_p1_ocr_markdown_flash_parse_repair_20260518/flash_repair3/flash_summary.json",
        "p1_parse_repair_merge": "reports/v6_p1_ocr_markdown_flash_parse_repair_20260518/parse_repair_merge_summary.json",
        "p1_stable_repaired_summary": "reports/v6_p1_ocr_markdown_flash_full1082_stable_extract_repaired_20260518/stable_materialize_summary.json",
        "p1_promotion_verify": "reports/graph_production_promotion_v6_p1_ocr_markdown_flash_full1082_verify_20260518/promotion_report.json",
        "p1_locator_after_local_ocr": "reports/v6_p1_existing_ocr_locator_after_local_ocr_full_strict_20260518/v6_p1_existing_ocr_locator_summary.json",
        "p1_local_ocr_repair_summary": "reports/v6_p1_local_ocr_repair_20260518/full_remaining_20260518_1458/local_ocr_repair_summary.json",
        "p1_incremental_flash_summary": "reports/v6_p1_local_ocr_markdown_flash_incremental_287_20260518/flash_run287/flash_summary.json",
        "p1_incremental_stable_summary": "reports/v6_p1_local_ocr_markdown_flash_incremental_287_stable_extract_20260518/stable_materialize_summary.json",
        "p1_incremental_promotion_verify": "reports/graph_production_promotion_v6_p1_local_ocr_flash_incremental_287_verify_20260518/promotion_report.json",
        "p1_second_pass_locator": "reports/v6_p1_existing_ocr_locator_after_second_pass_20260518/v6_p1_existing_ocr_locator_summary.json",
        "p1_second_pass_ocr_repair_summary": "reports/v6_p1_local_ocr_repair_20260518/second_pass_69_20260518_1610/local_ocr_repair_summary.json",
        "p1_second_pass_flash_summary": "reports/v6_p1_local_ocr_second_pass_flash_incremental_28_20260518/flash_run28/flash_summary.json",
        "p1_second_pass_stable_summary": "reports/v6_p1_local_ocr_second_pass_flash_incremental_28_stable_extract_20260518/stable_materialize_summary.json",
        "p1_second_pass_promotion_verify": "reports/graph_production_promotion_v6_p1_local_ocr_second_pass_flash_incremental_28_verify_20260518/promotion_report.json",
        "merged_stable_summary": "reports/stable_merge_47k_plus_v6_p1_repair_1397_20260518/stable_merge_summary.json",
        "merged_readiness_packet": "reports/v6_47k_merge_readiness_packet_20260518/v6_47k_merge_readiness_packet.json",
        "merged_graph_promotion_verify": "reports/graph_production_promotion_47k_plus_v6_p1_repair_1397_verify_20260518/promotion_report.json",
        "external_roots": "reports/stage7_external_data_roots_validation_20260518/external_data_roots_validation_packet.json",
        "crash_guard": "reports/crash_dump_guard_20260518/crash_dump_guard_report.json",
        "p1_ocr_locator": "reports/v6_p1_existing_ocr_locator_20260518/v6_p1_existing_ocr_locator_summary.json",
    }
    loaded = {key: read_json(root / value) for key, value in inputs.items()}
    items = build_gap_items(**loaded)
    blockers = [key for key, exists in count_existing(inputs).items() if not exists]
    item_by_id = {item["gap_id"]: item for item in items}
    p1 = next((item for item in items if item["gap_id"] == "v6_image_bucket_visual_loss"), {})
    p1_base = item_by_id.get("v6_p1_existing_ocr_markdown_repair_subgraph", {})
    p1_incremental = item_by_id.get("v6_p1_local_ocr_static_frame_incremental287_repair_subgraph", {})
    p1_second_pass = item_by_id.get("v6_p1_local_ocr_second_pass_incremental28_repair_subgraph", {})
    merged_graph = item_by_id.get("merged_47k_plus_v6_p1_repair_graph_lane", {})
    v6_baseline = item_by_id.get("v6_81k_structured_baseline", {})
    p1_total_estimated_cny = None
    if any(
        isinstance(value, (int, float))
        for value in (p1_base.get("total_estimated_cny"), p1_incremental.get("flash_estimated_cny"), p1_second_pass.get("flash_estimated_cny"))
    ):
        p1_total_estimated_cny = round(
            float(p1_base.get("total_estimated_cny") or 0)
            + float(p1_incremental.get("flash_estimated_cny") or 0)
            + float(p1_second_pass.get("flash_estimated_cny") or 0),
            4,
        )
    paid_ocr = item_by_id.get("paid_ocr_432_repair_subgraph", {})
    external = item_by_id.get("external_user_roots", {})
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": not blockers,
        "decision": "data_completeness_gap_ledger_ready" if not blockers else "data_completeness_gap_ledger_missing_inputs",
        "input_paths": inputs,
        "missing_inputs": blockers,
        "summary": {
            "current_text_graph_articles": items[0].get("article_count"),
            "current_text_graph_entities": items[0].get("entity_count"),
            "current_text_graph_events": items[0].get("event_count"),
            "current_47k_plus_p1_graph_articles": merged_graph.get("promoted_article"),
            "current_47k_plus_p1_graph_entities": merged_graph.get("promoted_entity"),
            "current_47k_plus_p1_graph_events": merged_graph.get("promoted_event"),
            "merged_47k_plus_p1_stable_articles": merged_graph.get("stable_articles"),
            "v6_structured_rows": v6_baseline.get("processed_samples"),
            "v6_image_bucket_rows_text_only_flash": p1.get("image_bucket_rows"),
            "p1_likely_visual_missing_rows": p1.get("p1_likely_visual_missing"),
            "p1_existing_ocr_text_rows": p1.get("existing_ocr_covered_rows"),
            "p1_ocr_quality_accepted_rows": p1.get("ocr_quality_accepted_rows"),
            "p1_merge_ready_rows": p1.get("merge_ocr_markdown_flash_ready"),
            "p1_merge_ready_articles_promoted": p1.get("merge_ready_promoted_to_graph"),
            "p1_remaining_local_ocr_rerun_rows": p1.get("remaining_local_ocr_rerun_needed"),
            "p1_low_quality_text_review_rows": p1.get("ocr_low_quality_text_review_needed"),
            "p1_local_ocr_rerun_rows": p1.get("ocr_rerun_needed"),
            "p1_paid_recapture_needed_rows": p1.get("recapture_or_external_locator_needed"),
            "p1_ocr_markdown_repair_articles_promoted": (p1_base.get("promoted_article") or 0)
            + (p1_incremental.get("promoted_article") or 0)
            + (p1_second_pass.get("promoted_article") or 0),
            "p1_ocr_markdown_repair_entities_promoted": (p1_base.get("promoted_entity") or 0)
            + (p1_incremental.get("promoted_entity") or 0)
            + (p1_second_pass.get("promoted_entity") or 0),
            "p1_ocr_markdown_repair_events_promoted": (p1_base.get("promoted_event") or 0)
            + (p1_incremental.get("promoted_event") or 0)
            + (p1_second_pass.get("promoted_event") or 0),
            "p1_ocr_markdown_repair_total_estimated_cny": p1_total_estimated_cny,
            "p1_local_ocr_frames_extracted": (p1_incremental.get("local_ocr_frames_extracted") or 0) + (p1_second_pass.get("local_ocr_frames_extracted") or 0),
            "p1_local_ocr_incremental_articles_promoted": p1_incremental.get("promoted_article"),
            "p1_local_ocr_second_pass_articles_promoted": p1_second_pass.get("promoted_article"),
            "paid_ocr_repair_articles_promoted": paid_ocr.get("promoted_article"),
            "external_roots_validation_only": external.get("root_count"),
        },
        "gap_items": items,
        "safety": {
            "d_scan_executed": False,
            "ocr_execution": False,
            "deepseek_api_used": False,
            "paid_api_used": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "production_publish_executed": False,
            "report_only": True,
        },
        "next_order": [
            "Treat the 1,397 strict P1 OCR-repaired rows as complete in the local production graph marker.",
            "Review the 99 low-quality OCR text rows separately; do not auto-send them to Flash.",
            "For the remaining 30 OCR-empty P1 rows, stop local OCR unless a new high-signal strategy is justified.",
            "Do not run paid recapture for current P1 unless a new source-image locator proves missing local evidence.",
            "Treat the 46,965-row 47K+P1 repair graph marker as complete; do not treat this as full V6 81K promotion.",
        ],
    }
    return report, items


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Data Completeness Gap Ledger",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- current_text_graph_articles: `{report['summary'].get('current_text_graph_articles')}`",
        f"- current_47k_plus_p1_graph_articles: `{report['summary'].get('current_47k_plus_p1_graph_articles')}`",
        f"- merged_47k_plus_p1_stable_articles: `{report['summary'].get('merged_47k_plus_p1_stable_articles')}`",
        f"- v6_structured_rows: `{report['summary'].get('v6_structured_rows')}`",
        f"- v6_image_bucket_rows_text_only_flash: `{report['summary'].get('v6_image_bucket_rows_text_only_flash')}`",
        f"- p1_likely_visual_missing_rows: `{report['summary'].get('p1_likely_visual_missing_rows')}`",
        f"- p1_existing_ocr_text_rows: `{report['summary'].get('p1_existing_ocr_text_rows')}`",
        f"- p1_ocr_quality_accepted_rows: `{report['summary'].get('p1_ocr_quality_accepted_rows')}`",
        f"- p1_merge_ready_rows: `{report['summary'].get('p1_merge_ready_rows')}`",
        f"- p1_merge_ready_articles_promoted: `{report['summary'].get('p1_merge_ready_articles_promoted')}`",
        f"- p1_remaining_local_ocr_rerun_rows: `{report['summary'].get('p1_remaining_local_ocr_rerun_rows')}`",
        f"- p1_low_quality_text_review_rows: `{report['summary'].get('p1_low_quality_text_review_rows')}`",
        f"- p1_local_ocr_rerun_rows: `{report['summary'].get('p1_local_ocr_rerun_rows')}`",
        f"- p1_paid_recapture_needed_rows: `{report['summary'].get('p1_paid_recapture_needed_rows')}`",
        f"- p1_ocr_markdown_repair_articles_promoted: `{report['summary'].get('p1_ocr_markdown_repair_articles_promoted')}`",
        f"- p1_ocr_markdown_repair_total_estimated_cny: `{report['summary'].get('p1_ocr_markdown_repair_total_estimated_cny')}`",
        f"- paid_ocr_repair_articles_promoted: `{report['summary'].get('paid_ocr_repair_articles_promoted')}`",
        "",
        "## Gap Items",
        "",
        "| Gap | Status | Count Signal | Next |",
        "|---|---|---:|---|",
    ]
    for item in report["gap_items"]:
        count_signal = (
            item.get("article_count")
            or item.get("processed_samples")
            or item.get("p1_likely_visual_missing")
            or item.get("input_rows")
            or item.get("stable_articles")
            or item.get("ocr_ready_rows")
            or item.get("root_count")
            or item.get("needs_ocr_remaining")
            or ""
        )
        lines.append(f"| `{item['gap_id']}` | `{item['status']}` | {count_signal} | {item['next_action']} |")
    lines.extend(["", "## Next Order", ""])
    for step in report["next_order"]:
        lines.append(f"- {step}")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(report["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report, items = build_report(args.root)
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "gap_ledger.json", report)
    write_jsonl(out_dir / "gap_items.jsonl", items)
    write_markdown(out_dir / "gap_ledger.md", report)
    print(json.dumps({"ok": report["ok"], "decision": report["decision"], "out_dir": str(out_dir)}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
