#!/usr/bin/env python3
"""Summarize Stage7 PRD longrun status from local evidence artifacts.

This script is report-only. It reads LONGRUN_STATE and existing JSON reports,
then emits a single machine-readable scoreboard for the remaining PRD pipeline.
It does not call external services and does not write DB/vector/graph state.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OUT_DIR = Path("reports/prd_longrun_status_20260515")
MONEY_NOT_ENOUGH_MARKER = "\u91d1\u989d\u4e0d\u8db3"


KEY_REPORTS = {
    "neo4j_p1": Path("reports/neo4j_p1_social_staging_20260515/canary_verification.json"),
    "cdcr": Path("reports/p1_cdcr_direct_source_20260515/cdcr_direct_source_summary.json"),
    "cdcr_review": Path("reports/p1_cdcr_direct_source_review_20260516/cdcr_direct_source_review_summary.json"),
    "consumer_publish_gate": Path(
        "reports/consumer_publish_gate_review_47k_plus_v6_p1_repair_1397_20260518/consumer_publish_gate_review.json"
    ),
    "consumer_production_gate_packet": Path(
        "reports/consumer_production_gate_packet_47k_plus_v6_p1_repair_1397_20260518/consumer_production_gate_packet.json"
    ),
    "cloudrun_deploy_execution": Path(
        "reports/full_pipeline_production_deploy_47k_plus_v6_p1_repair_1397_20260518/cloudrun_deploy_execution_report.json"
    ),
    "cloudrun_stage7_production_smoke": Path(
        "reports/cloudrun_stage7_production_smoke_47k_plus_v6_p1_repair_1397_20260518/cloudrun_stage7_production_smoke.json"
    ),
    "cloudrun_weekly_production_smoke": Path(
        "reports/cloudrun_weekly_production_smoke_47k_plus_v6_p1_repair_1397_20260518/cloudrun_weekly_production_smoke.json"
    ),
    "publish_time_consolidated": Path(
        "reports/publish_time_consolidated_20260515/publish_time_consolidated_summary.json"
    ),
    "ocr_queue": Path("reports/ocr_canary_queue_20260515/ocr_canary_queue_summary.json"),
    "ocr_v30_coverage": Path(
        "reports/ocr_root_cause_20260515/"
        "corrected_full_stable_extract_v30_deepseek_recovered1217_20260515/"
        "coverage_vs_fixed_routes.json"
    ),
    "ocr_v30_merge": Path(
        "reports/ocr_root_cause_20260515/"
        "corrected_full_stable_extract_v30_deepseek_recovered1217_20260515/"
        "stable_merge_summary.json"
    ),
    "non_dajiala": Path("reports/ocr_root_cause_20260515/non_dajiala_recoverability_audit_v30_20260515/summary.json"),
    "ocr_asset_synthesis": Path("reports/ocr_asset_blocker_synthesis_20260515/ocr_asset_blocker_synthesis.json"),
    "dajiala_canary": Path("reports/ocr_root_cause_20260515/empty_no_local_image_dajiala_canary_20260515/dajiala_canary_report.json"),
    "dajiala_roi_budget_gate_packet": Path(
        "reports/dajiala_roi_budget_gate_packet_20260518/dajiala_roi_budget_gate_packet.json"
    ),
    "dajiala_paid_wave_execution_packet": Path(
        "reports/dajiala_paid_wave07_execution_packet_20260518/dajiala_paid_wave_execution_packet.json"
    ),
    "dajiala_paid_latest_archive_status": Path(
        "reports/dajiala_paid_wave07_archive_20260517/dajiala-repair-status.json"
    ),
    "poster_preflight": Path("reports/poster_vector_preflight_20260515/poster_vector_preflight_summary.json"),
    "dajiala_verified_ocr_index": Path(
        "reports/dajiala_paid_wave01_07_verified_combined_ocr_index_20260518/ocr_file_index_summary.json"
    ),
    "dajiala_verified_poster_preflight": Path(
        "reports/dajiala_paid_wave07_poster_vector_preflight_20260518/"
        "poster_vector_preflight_summary.json"
    ),
    "dajiala_verified_poster_text_vector_jobs": Path(
        "reports/dajiala_paid_wave01_07_verified_poster_text_vector_jobs_20260518/"
        "poster_text_vector_jobs_summary.json"
    ),
    "poster_vector_write_gate_packet": Path(
        "reports/poster_vector_write_gate_packet_wave01_07_20260518/poster_vector_write_gate_packet.json"
    ),
    "qdrant_poster_staging": Path(
        "reports/qdrant_poster_staging_wave01_07_20260518/qdrant_poster_staging_report.json"
    ),
    "poster_text_gate_refresh": Path(
        "reports/poster_ocr_text_gate_refresh_20260515/poster_ocr_text_gate_refresh.json"
    ),
    "social_deep_edges": Path("reports/social_deep_edge_pack_20260515/social_deep_edge_pack_summary.json"),
    "social_identity_review": Path(
        "reports/social_identity_cross_evidence_20260515/identity_cross_evidence_summary.json"
    ),
    "opencli_social_profile_evidence": Path(
        "reports/opencli_social_profile_evidence_20260516/social_profile_evidence_summary.json"
    ),
    "opencli_social_identity_review": Path(
        "reports/opencli_social_identity_review_20260516/opencli_identity_review_summary.json"
    ),
    "social_identity_acceptance_gate_packet": Path(
        "reports/social_identity_acceptance_gate_packet_20260517/social_identity_acceptance_gate_packet.json"
    ),
    "identity_neo4j_staging_gate_packet": Path(
        "reports/identity_neo4j_staging_gate_packet_20260517/identity_neo4j_staging_gate_packet.json"
    ),
    "storage_snapshot": Path("reports/storage_migration_20260515/snapshot_phase2_summary.json"),
    "mem0_gate": Path("reports/mem0_dimension_gate_20260516/mem0_dimension_gate.json"),
    "mem0_write_gate_packet": Path("reports/mem0_write_gate_packet_20260518/mem0_write_gate_packet.json"),
    "mem0_local_canary": Path("reports/mem0_local_write_read_canary_20260518/mem0_local_write_read_canary.json"),
    "weekly_path": Path("reports/weekly_publish_path_decision_20260515/weekly_publish_path_decision.json"),
    "canonical_entities": Path("reports/canonical_entities_20260515/canonical_entities_summary.json"),
    "canonical_fuzzy_review_gate_packet": Path(
        "reports/canonical_fuzzy_review_gate_packet_20260517/canonical_fuzzy_review_gate_packet.json"
    ),
    "graph_promotion_readiness": Path(
        "reports/graph_promotion_readiness_47k_plus_v6_p1_repair_1397_20260518/graph_promotion_readiness.json"
    ),
    "graph_production_promotion_verify": Path(
        "reports/graph_production_promotion_47k_plus_v6_p1_repair_1397_verify_20260518/promotion_report.json"
    ),
    "consumer_deploy_readiness": Path(
        "reports/consumer_deploy_readiness_47k_plus_v6_p1_repair_1397_20260518/consumer_deploy_readiness.json"
    ),
    "ocr_entity_extraction": Path("reports/ocr_entity_extraction_20260515/ocr_entity_extraction_summary.json"),
    "dajiala_verified_ocr_entity_extraction": Path(
        "reports/dajiala_paid_wave01_07_verified_ocr_entity_extraction_20260518/ocr_entity_extraction_summary.json"
    ),
    "dajiala_verified_ocr_entity_merge": Path(
        "reports/dajiala_paid_wave01_07_verified_ocr_entity_merge_plan_20260518/ocr_entity_merge_report.json"
    ),
    "ocr_entity_merge_write_gate_packet": Path(
        "reports/ocr_entity_merge_write_gate_packet_wave01_07_20260518/ocr_entity_merge_write_gate_packet.json"
    ),
    "ocr_entity_merge": Path("reports/ocr_entity_merge_20260515/ocr_entity_merge_report.json"),
    "ocr_reflow_readiness": Path("reports/ocr_reflow_readiness_20260515/ocr_reflow_readiness.json"),
    "ocr_sidecar_entity_extraction": Path(
        "reports/ocr_sidecar_entity_extraction_20260515/ocr_sidecar_entity_extraction_summary.json"
    ),
    "ocr_sidecar_entity_merge": Path("reports/ocr_sidecar_entity_merge_20260515/ocr_entity_merge_report.json"),
    "hybrid_recommend": Path(
        "reports/hybrid_recommend_canary_47k_plus_v6_p1_repair_1397_20260518/hybrid_recommend_canary.json"
    ),
    "hermes_alerts": Path("reports/hermes_alerts_20260515/alerts.json"),
    "graph_rag_answer": Path(
        "reports/graph_rag_answer_47k_plus_v6_p1_repair_1397_20260518/graph_rag_answer_summary.json"
    ),
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(root: Path, rel: Path) -> dict[str, Any] | None:
    path = root / rel
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{rel} must contain a JSON object")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def nested_get(value: dict[str, Any] | None, path: tuple[str, ...], default: Any = None) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def artifact(root: Path, rel: Path, payload: dict[str, Any] | None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "path": str(rel).replace("/", "\\"),
        "exists": (root / rel).exists(),
    }
    if payload:
        for key in ("schema_version", "decision", "ok", "status", "generated_at"):
            if key in payload:
                data[key] = payload[key]
        decision = nested_get(payload, ("decision", "status"))
        if decision:
            data["decision_status"] = decision
    return data


def evidence(root: Path, reports: dict[str, dict[str, Any] | None], keys: list[str]) -> list[dict[str, Any]]:
    return [artifact(root, KEY_REPORTS[key], reports.get(key)) for key in keys]


def prd(
    prd_id: str,
    title: str,
    status: str,
    production_ready: bool,
    evidence_items: list[dict[str, Any]],
    blockers: list[str] | None = None,
    next_safe_action: str = "",
    metrics: dict[str, Any] | None = None,
    writes: str = "reports_only_or_staging_only",
) -> dict[str, Any]:
    return {
        "id": prd_id,
        "title": title,
        "status": status,
        "production_ready": production_ready,
        "writes": writes,
        "blockers": blockers or [],
        "next_safe_action": next_safe_action,
        "metrics": metrics or {},
        "evidence": evidence_items,
    }


def build_status(root: Path) -> dict[str, Any]:
    reports = {key: read_json(root, rel) for key, rel in KEY_REPORTS.items()}
    longrun_path = root / "LONGRUN_STATE.md"
    longrun_text = longrun_path.read_text(encoding="utf-8", errors="replace") if longrun_path.exists() else ""
    has_balance_blocker = MONEY_NOT_ENOUGH_MARKER in longrun_text or "balance" in longrun_text.lower()

    ocr_coverage = reports["ocr_v30_coverage"] or {}
    ocr_merge = reports["ocr_v30_merge"] or {}
    non_dajiala = reports["non_dajiala"] or {}
    ocr_asset_synthesis = reports["ocr_asset_synthesis"] or {}
    cdcr_review = reports["cdcr_review"] or {}
    consumer_gate = reports["consumer_publish_gate"] or {}
    consumer_production_gate_packet = reports["consumer_production_gate_packet"] or {}
    cloudrun_deploy_execution = reports["cloudrun_deploy_execution"] or {}
    cloudrun_stage7_production_smoke = reports["cloudrun_stage7_production_smoke"] or {}
    cloudrun_weekly_production_smoke = reports["cloudrun_weekly_production_smoke"] or {}
    dajiala_roi_budget_gate_packet = reports["dajiala_roi_budget_gate_packet"] or {}
    dajiala_paid_wave_execution_packet = reports["dajiala_paid_wave_execution_packet"] or {}
    dajiala_paid_latest_archive_status = reports["dajiala_paid_latest_archive_status"] or {}
    poster_preflight = reports["poster_preflight"] or {}
    dajiala_verified_index = reports["dajiala_verified_ocr_index"] or {}
    dajiala_verified_poster_preflight = reports["dajiala_verified_poster_preflight"] or {}
    dajiala_verified_poster_text_vector_jobs = reports["dajiala_verified_poster_text_vector_jobs"] or {}
    poster_vector_write_gate_packet = reports["poster_vector_write_gate_packet"] or {}
    poster_text_refresh = reports["poster_text_gate_refresh"] or {}
    social_identity_review = reports["social_identity_review"] or {}
    opencli_identity_review = reports["opencli_social_identity_review"] or {}
    social_identity_acceptance_gate_packet = reports["social_identity_acceptance_gate_packet"] or {}
    identity_neo4j_staging_gate_packet = reports["identity_neo4j_staging_gate_packet"] or {}
    weekly_path = reports["weekly_path"] or {}
    canonical_summary = reports["canonical_entities"] or {}
    canonical_fuzzy_review_gate_packet = reports["canonical_fuzzy_review_gate_packet"] or {}
    graph_promotion = reports["graph_promotion_readiness"] or {}
    graph_production_promotion_verify = reports["graph_production_promotion_verify"] or {}
    deploy_readiness = reports["consumer_deploy_readiness"] or {}
    ocr_reflow = reports["ocr_reflow_readiness"] or {}
    sidecar_extraction = reports["ocr_sidecar_entity_extraction"] or {}
    sidecar_merge = reports["ocr_sidecar_entity_merge"] or {}
    dajiala_verified_entity_extraction = reports["dajiala_verified_ocr_entity_extraction"] or {}
    dajiala_verified_entity_merge = reports["dajiala_verified_ocr_entity_merge"] or {}
    ocr_entity_merge_write_gate_packet = reports["ocr_entity_merge_write_gate_packet"] or {}
    mem0_gate = reports["mem0_gate"] or {}
    mem0_write_gate_packet = reports["mem0_write_gate_packet"] or {}
    mem0_local_canary = reports["mem0_local_canary"] or {}
    storage_snapshot = reports["storage_snapshot"] or {}

    ocr_missing = int(nested_get(ocr_coverage, ("totals", "fixed_route_missing_from_v30_unique"), 0) or 0)
    stable_unique = int(ocr_coverage.get("stable_unique") or ocr_merge.get("articles") or 0)
    recovered_empty = int(nested_get(ocr_merge, ("lane_counts", "empty_no_local_image"), 0) or 0)
    non_dajiala_missing = int(non_dajiala.get("missing_count") or 0)
    non_dajiala_image_evidence = any(
        int((non_dajiala.get("field_positive_counts") or {}).get(key) or 0) > 0
        for key in (
            "existing_local_image_count_gt0",
            "local_image_count_gt0",
            "remote_image_count_gt0",
            "archive_asset_image_count_gt0",
            "processed_asset_image_count_gt0",
            "sidecar_image_count_gt0",
        )
    )
    publish_blockers = list(consumer_gate.get("blocking_reasons") or [])
    poster_blockers = list(poster_preflight.get("blockers") or [])
    verified_text_ready_rows = int(dajiala_verified_poster_preflight.get("text_ready_poster_rows") or 0)
    verified_local_image_rows = int(dajiala_verified_poster_preflight.get("local_image_rows") or 0)
    verified_poster_text_gate_ready = (
        dajiala_verified_poster_preflight.get("decision") == "poster_vectorization_preflight_ready"
        and bool(dajiala_verified_poster_preflight.get("text_gate_met"))
        and verified_text_ready_rows >= 20
        and verified_local_image_rows >= 20
    )
    verified_poster_job_count = int(dajiala_verified_poster_text_vector_jobs.get("job_count") or 0)
    verified_poster_text_vector_jobs_ready = (
        dajiala_verified_poster_text_vector_jobs.get("decision") == "poster_text_vector_jobs_ready_report_only"
        and verified_poster_job_count >= 20
        and not bool(nested_get(dajiala_verified_poster_text_vector_jobs, ("safety", "embedding_calls"), True))
        and not bool(nested_get(dajiala_verified_poster_text_vector_jobs, ("safety", "qdrant_write"), True))
    )
    poster_vector_write_gate_packet_ready = (
        poster_vector_write_gate_packet.get("decision") == "poster_vector_write_gate_packet_ready_report_only"
    )
    poster_vector_write_hard_gates = list(poster_vector_write_gate_packet.get("hard_gates_remaining") or [])
    poster_vector_staging_evidence = poster_vector_write_gate_packet.get("poster_staging_evidence") or {}
    poster_vector_staging_written = (
        poster_vector_write_gate_packet_ready
        and bool(poster_vector_staging_evidence.get("evidence_ready"))
        and not poster_vector_write_hard_gates
    )
    weekly_blocked_paths = weekly_path.get("blocked_paths") or []
    canonical_ready = bool(canonical_summary.get("ok"))
    canonical_fuzzy_review_gate_packet_ready = (
        canonical_fuzzy_review_gate_packet.get("decision") == "canonical_fuzzy_review_gate_ready_report_only"
        and bool(canonical_fuzzy_review_gate_packet.get("future_fuzzy_merge_write_deferred"))
    )
    graph_promotion_report_ready = bool(graph_promotion.get("ok"))
    deploy_readiness_report_ready = bool(deploy_readiness.get("ok"))
    cloudrun_deploy_report_ready = cloudrun_deploy_execution.get("decision") in {
        "cloudrun_deploy_verified",
        "cloudrun_deploy_blocked_external_cli",
    }
    cloudrun_deploy_verified = bool(cloudrun_deploy_execution.get("ok")) and bool(
        nested_get(cloudrun_deploy_execution, ("safety", "cloud_deploy_executed"))
    )
    cloudrun_production_smoke_ready = (
        bool(cloudrun_stage7_production_smoke.get("ok"))
        and cloudrun_stage7_production_smoke.get("decision") == "cloudrun_stage7_production_smoke_ready"
    )
    cloudrun_weekly_production_smoke_ready = (
        bool(cloudrun_weekly_production_smoke.get("ok"))
        and cloudrun_weekly_production_smoke.get("decision") == "cloudrun_weekly_production_smoke_ready"
    )
    graph_production_promotion_verified = bool(graph_production_promotion_verify.get("ok")) and bool(
        nested_get(graph_production_promotion_verify, ("verification", "ok"))
    )
    ocr_reflow_report_ready = bool(ocr_reflow.get("ok"))
    poster_text_refresh_done = poster_text_refresh.get("decision") in {
        "poster_ocr_text_gate_ready_official_index",
        "poster_ocr_text_gate_sidecar_ready_official_contract_blocked",
        "poster_ocr_text_gate_blocked_missing_real_text",
    }
    social_identity_review_done = social_identity_review.get("decision") in {
        "social_identity_cross_evidence_review_ready",
        "social_identity_cross_evidence_empty",
    }
    opencli_identity_review_done = opencli_identity_review.get("decision") == "opencli_identity_review_ready"
    ocr_asset_synthesis_done = (
        ocr_asset_synthesis.get("decision") == "ocr_asset_recovery_blocked_external_paid_and_no_nonpaid_image_source"
    )
    sidecar_entity_count = int(sidecar_extraction.get("entity_count") or 0)
    sidecar_min_entities = int(sidecar_extraction.get("min_entities") or 10)
    sidecar_would_merge = int(sidecar_merge.get("would_merge_entities") or 0)
    sidecar_merge_ready = bool(sidecar_merge.get("ok")) or sidecar_merge.get("decision") == "ocr_entity_merge_dry_run_ready"
    sidecar_ready = (
        bool(sidecar_extraction.get("ok"))
        and sidecar_merge_ready
        and sidecar_entity_count >= sidecar_min_entities
        and sidecar_would_merge == sidecar_entity_count
    )
    verified_entity_count = int(dajiala_verified_entity_extraction.get("entity_count") or 0)
    verified_entity_ready = (
        dajiala_verified_entity_extraction.get("decision") == "ocr_entity_extraction_ready"
        and bool(dajiala_verified_entity_extraction.get("gate_met"))
        and verified_entity_count >= int(dajiala_verified_entity_extraction.get("min_entities") or 10)
    )
    verified_would_merge = int(dajiala_verified_entity_merge.get("would_merge_entities") or 0)
    verified_merge_ready = (
        dajiala_verified_entity_merge.get("decision") == "ocr_entity_merge_dry_run_ready"
        and not bool(dajiala_verified_entity_merge.get("mutation_executed"))
        and verified_would_merge > 0
    )
    ocr_entity_merge_write_gate_packet_ready = (
        ocr_entity_merge_write_gate_packet.get("decision")
        in {"ocr_entity_merge_write_gate_packet_ready_report_only", "ocr_entity_merge_staging_written"}
    )
    ocr_entity_merge_staging_written = (
        ocr_entity_merge_write_gate_packet.get("decision") == "ocr_entity_merge_staging_written"
    )
    cdcr_review_ready = cdcr_review.get("decision") == "cdcr_direct_source_review_ready"
    social_identity_acceptance_gate_packet_ready = (
        social_identity_acceptance_gate_packet.get("decision")
        == "social_identity_acceptance_gate_packet_ready_report_only"
    )
    identity_neo4j_staging_gate_packet_ready = (
        identity_neo4j_staging_gate_packet.get("decision")
        in {"identity_neo4j_staging_gate_packet_ready_report_only", "identity_neo4j_staging_canary_written"}
    )
    identity_neo4j_staging_hard_gates = list(identity_neo4j_staging_gate_packet.get("hard_gates_remaining") or [])
    identity_neo4j_staging_authorized = bool(identity_neo4j_staging_gate_packet.get("neo4j_staging_write_allowed"))
    identity_neo4j_staging_canary_executed = bool(identity_neo4j_staging_gate_packet.get("neo4j_staging_canary_executed"))
    graph_promotion_allowed = bool(graph_promotion.get("promotion_allowed"))
    social_identity_accepted_edges_by_scope = social_identity_acceptance_gate_packet.get("accepted_edges_by_scope") or {}
    strict_prd16_accepted_edges = int(
        social_identity_accepted_edges_by_scope.get("strict_prd16")
        or social_identity_acceptance_gate_packet.get("accepted_edges_total")
        or 0
    )
    cdcr_strict_accepted_edges = int(social_identity_accepted_edges_by_scope.get("cdcr_strict") or 0)
    strict_cdcr_overlap_accepted_edges = int(
        social_identity_accepted_edges_by_scope.get("strict_cdcr_subject_overlap") or 0
    )
    consumer_gate_packet_ready = (
        consumer_production_gate_packet.get("decision") == "consumer_production_gate_packet_ready_report_only"
    )
    consumer_production_hard_gates = list(consumer_production_gate_packet.get("hard_gates_remaining") or [])
    consumer_production_policy_blocked = any(
        "production_publish" in str(item).casefold()
        or "production_sqlite" in str(item).casefold()
        or "unknown_time_business_acceptance" in str(item).casefold()
        or "globally forbidden" in str(item).casefold()
        for item in consumer_production_hard_gates
    )
    dajiala_roi_budget_gate_packet_ready = (
        dajiala_roi_budget_gate_packet.get("decision") == "dajiala_roi_budget_gate_packet_ready_report_only"
    )
    dajiala_paid_wave_decision = dajiala_paid_wave_execution_packet.get("decision")
    dajiala_paid_wave_execution_packet_ready = dajiala_paid_wave_decision in {
        "dajiala_paid_wave_execution_ready",
        "dajiala_paid_wave_execution_ready_key_missing",
    }
    dajiala_paid_wave_execution_allowed = dajiala_paid_wave_decision == "dajiala_paid_wave_execution_ready"
    dajiala_paid_wave_execution_key_missing = (
        dajiala_paid_wave_decision == "dajiala_paid_wave_execution_ready_key_missing"
    )
    paid_latest_total = int(dajiala_paid_latest_archive_status.get("totalItems") or 0)
    paid_latest_succeeded = int(dajiala_paid_latest_archive_status.get("succeededCount") or 0)
    paid_latest_failed = int(dajiala_paid_latest_archive_status.get("failedCount") or 0)
    paid_latest_success_rate = (paid_latest_succeeded / paid_latest_total) if paid_latest_total else 0.0
    paid_latest_completed = dajiala_paid_latest_archive_status.get("status") == "completed" and paid_latest_total > 0
    paid_latest_success_green = paid_latest_completed and paid_latest_success_rate >= 0.30
    mem0_status = nested_get(mem0_gate, ("decision", "status"))
    mem0_write_gate_packet_ready = (
        mem0_write_gate_packet.get("decision")
        in {"mem0_write_gate_packet_ready_report_only", "mem0_local_write_read_canary_passed"}
    )
    mem0_local_canary_passed = (
        mem0_write_gate_packet.get("decision") == "mem0_local_write_read_canary_passed"
        and bool(mem0_write_gate_packet.get("ok"))
        and bool(nested_get(mem0_write_gate_packet, ("safety", "mem0_write_executed")))
    )

    prds = [
        prd(
            "PRD-01",
            "Neo4j Social Staging Canary",
            "staging_complete",
            False,
            evidence(root, reports, ["neo4j_p1"]),
            next_safe_action="Keep edges staging-only until PRD-07/PRD-08 gates pass.",
            writes="staging_only_neo4j",
        ),
        prd(
            "PRD-02",
            "CDCR Direct Source Collection",
            (
                "identity_neo4j_staging_canary_written"
                if identity_neo4j_staging_gate_packet_ready
                and (cdcr_strict_accepted_edges + strict_cdcr_overlap_accepted_edges) > 0
                and identity_neo4j_staging_canary_executed
                else "identity_neo4j_staging_gate_packet_ready_write_authorized"
                if identity_neo4j_staging_gate_packet_ready
                and (cdcr_strict_accepted_edges + strict_cdcr_overlap_accepted_edges) > 0
                and identity_neo4j_staging_authorized
                and not identity_neo4j_staging_hard_gates
                else "identity_neo4j_staging_gate_packet_ready_graph_write_blocked"
                if identity_neo4j_staging_gate_packet_ready
                and (cdcr_strict_accepted_edges + strict_cdcr_overlap_accepted_edges) > 0
                else "identity_acceptance_gate_cdcr_strict_edges_ready_graph_write_blocked"
                if social_identity_acceptance_gate_packet_ready
                and (cdcr_strict_accepted_edges + strict_cdcr_overlap_accepted_edges) > 0
                else "identity_acceptance_gate_packet_ready_graph_blocked"
                if social_identity_acceptance_gate_packet_ready
                and strict_cdcr_overlap_accepted_edges == 0
                else "identity_acceptance_gate_packet_cdcr_overlap_ready_graph_blocked"
                if social_identity_acceptance_gate_packet_ready
                else "direct_source_review_pack_ready_graph_blocked"
                if cdcr_review_ready
                else "report_complete_review_blocked"
            ),
            False,
            evidence(
                root,
                reports,
                ["cdcr", "cdcr_review", "social_identity_acceptance_gate_packet", "identity_neo4j_staging_gate_packet"],
            ),
            blockers=list(
                (
                    identity_neo4j_staging_hard_gates
                    if identity_neo4j_staging_gate_packet_ready
                    else
                    [
                        "PRD-02 CDCR strict accepted overlap remains 0",
                        "CDCR evidence is review-ready but not identity proof",
                        "Neo4j staging write is forbidden for identity candidates in this run",
                        "production graph labels are forbidden for this run",
                        "PRD-07 graph promotion is blocked",
                    ]
                    if strict_prd16_accepted_edges > 0 and strict_cdcr_overlap_accepted_edges == 0
                    and cdcr_strict_accepted_edges == 0
                    else social_identity_acceptance_gate_packet.get("hard_gates_remaining")
                )
                if social_identity_acceptance_gate_packet_ready
                else cdcr_review.get("blockers")
                if cdcr_review_ready
                else ["identity proof/review is not sufficient for graph promotion"]
            ),
            next_safe_action=(
                "Verify the Neo4j staging canary report, then keep production-label promotion on the PRD-07 lane."
                if identity_neo4j_staging_gate_packet_ready
                and identity_neo4j_staging_canary_executed
                else "Run the generated Neo4j staging canary command; keep production labels separate until verified."
                if identity_neo4j_staging_gate_packet_ready
                and identity_neo4j_staging_authorized
                and not identity_neo4j_staging_hard_gates
                else "Use identity Neo4j staging gate packet as report-only write readiness evidence."
                if identity_neo4j_staging_gate_packet_ready
                else
                "Use acceptance gate packet for source-backed row review; keep accepted CDCR graph edges empty until accepted."
                if social_identity_acceptance_gate_packet_ready
                else "Use source-backed/profile candidates for acceptance review; keep CDCR graph edges empty until accepted."
                if cdcr_review_ready
                else "Use as review input only; do not promote CDCR graph edges."
            ),
            metrics={
                "subject_count": cdcr_review.get("subject_count"),
                "direct_source_candidates": cdcr_review.get("direct_source_candidates"),
                "source_backed_profile_review_candidates": cdcr_review.get("source_backed_profile_review_candidates"),
                "supporting_direct_source_review_candidates": cdcr_review.get(
                    "supporting_direct_source_review_candidates"
                ),
                "accepted_edges": cdcr_review.get("accepted_edges"),
                "identity_acceptance_gate_candidates": social_identity_acceptance_gate_packet.get(
                    "review_candidates_total"
                ),
                "identity_acceptance_gate_accepted_edges": social_identity_acceptance_gate_packet.get(
                    "accepted_edges_total"
                ),
                "identity_acceptance_gate_accepted_edges_by_scope": social_identity_accepted_edges_by_scope,
                "identity_acceptance_gate_hard_gates_remaining_count": len(
                    social_identity_acceptance_gate_packet.get("hard_gates_remaining") or []
                ),
                "identity_neo4j_staging_writer_valid_edges": identity_neo4j_staging_gate_packet.get(
                    "writer_valid_edges"
                ),
                "identity_neo4j_staging_manifest_path": identity_neo4j_staging_gate_packet.get("manifest_path"),
                "identity_neo4j_staging_local_ready_gate_count": identity_neo4j_staging_gate_packet.get(
                    "local_ready_gate_count"
                ),
            },
        ),
        prd(
            "PRD-03",
            "Consumer Publish Gate Config",
            (
                "production_gate_packet_ready_publish_policy_blocked"
                if consumer_gate_packet_ready
                and consumer_production_policy_blocked
                else "production_gate_packet_ready_endpoint_weekly_blocked"
                if consumer_gate_packet_ready
                and consumer_production_hard_gates
                else "production_gate_packet_ready"
                if consumer_gate_packet_ready
                else "blocked_production_publish_policy"
            ),
            False,
            evidence(root, reports, ["consumer_publish_gate", "consumer_production_gate_packet"]),
            blockers=list(consumer_production_gate_packet.get("hard_gates_remaining") or publish_blockers),
            next_safe_action=(
                "Use production gate packet as the release checklist; do not flip unknown-time acceptance in this run."
                if consumer_gate_packet_ready
                else "Keep staging pointer usable; production publish needs explicit unknown-time acceptance and rollback gate."
            ),
            metrics={
                "publish_allowed": consumer_gate.get("publish_allowed"),
                "dry_run_ready": consumer_gate.get("dry_run_ready"),
                "missing_publish_time_articles": nested_get(consumer_gate, ("counts", "missing_publish_time_articles")),
                "local_ready_gate_count": consumer_production_gate_packet.get("local_ready_gate_count"),
                "hard_gates_remaining_count": len(consumer_production_gate_packet.get("hard_gates_remaining") or []),
            },
        ),
        prd(
            "PRD-04",
            "Publish Time Recovery",
            "report_complete_no_source_publish_time",
            False,
            evidence(root, reports, ["publish_time_consolidated"]),
            blockers=["no source-backed WeChat publish_time found in bounded probes"],
            next_safe_action="Only reopen if a new source-backed publish-time source is identified.",
        ),
        prd(
            "PRD-05",
            "OCR Bounded Canary",
            "dajiala_verified_ocr_index_ready_report_only" if verified_poster_text_gate_ready else "blocked_by_asset_source_gap",
            False,
            evidence(
                root,
                reports,
                ["ocr_queue", "ocr_v30_coverage", "non_dajiala", "ocr_asset_synthesis", "dajiala_verified_ocr_index"],
            ),
            blockers=(
                ["official production OCR promotion still forbidden; combined Dajiala OCR index is report-only"]
                if verified_poster_text_gate_ready
                else list(
                    ocr_asset_synthesis.get("blockers")
                    or [
                        f"{ocr_missing} fixed-route rows still missing after v30",
                        "remaining non-Dajiala lane has no image evidence" if not non_dajiala_image_evidence else "",
                    ]
                )
            ),
            next_safe_action=(
                "Use verified Dajiala OCR index as report-only input for PRD-12/13; no production promotion without write gates."
                if verified_poster_text_gate_ready
                else "Do not run fake OCR; reopen only from real local image assets or another source-backed recapture path."
            ),
            metrics={
                "verified_dajiala_ocr_rows": int(dajiala_verified_index.get("record_count") or 0),
                "verified_dajiala_existing_local_image_rows": (dajiala_verified_index.get("asset_counts") or {}).get(
                    "existing_local_image_gt0"
                ),
                "verified_dajiala_complete_rows": (dajiala_verified_index.get("ocr_status_counts") or {}).get("complete"),
            },
        ),
        prd(
            "PRD-05a",
            "OCR Asset Recovery",
            (
                "paid_recovery_report_ready_http_low_roi_stop"
                if verified_poster_text_gate_ready
                else "blocked_external_paid_and_no_nonpaid_image_source"
                if ocr_asset_synthesis_done
                else "partial_recovery_external_blocked"
            ),
            False,
            evidence(
                root,
                reports,
                ["ocr_v30_merge", "ocr_v30_coverage", "non_dajiala", "ocr_asset_synthesis", "dajiala_verified_ocr_index"],
            ),
            blockers=(
                ["remaining unrecovered rows still exist; further PRD-05a HTTP sampling stopped for low ROI"]
                if verified_poster_text_gate_ready
                else list(
                    ocr_asset_synthesis.get("blockers")
                    or [
                        f"stable_unique={stable_unique}, recovered_empty_no_local_image={recovered_empty}, missing={ocr_missing}",
                        "Dajiala paid wave blocked by account balance"
                        if has_balance_blocker
                        else "Dajiala paid wave not authorized",
                        f"non_dajiala_missing={non_dajiala_missing}, image_evidence={non_dajiala_image_evidence}",
                    ]
                )
            ),
            next_safe_action=(
                "Continue downstream report-only PRD-12/13 from the verified Dajiala OCR index; pause PRD-05a HTTP expansion."
                if verified_poster_text_gate_ready
                else (
                "Keep OCR/vector blocked until source-backed images appear or paid Dajiala balance gate is green."
                if ocr_asset_synthesis_done
                else "Continue only with non-paid source-backed repair, or resume paid waves after balance/key gate changes."
                )
            ),
            metrics={
                "stable_unique": stable_unique,
                "fixed_route_missing": ocr_asset_synthesis.get("fixed_route_missing", ocr_missing),
                "non_dajiala_image_evidence_present": nested_get(
                    ocr_asset_synthesis, ("non_dajiala", "image_evidence_present"), non_dajiala_image_evidence
                ),
                "dajiala_amount_not_enough": nested_get(ocr_asset_synthesis, ("dajiala_wave", "amount_not_enough")),
                "recovery_can_continue_without_new_source": ocr_asset_synthesis.get(
                    "recovery_can_continue_without_new_source"
                ),
                "verified_dajiala_ocr_rows": int(dajiala_verified_index.get("record_count") or 0),
            },
            writes="staging_artifacts_only",
        ),
        prd(
            "PRD-06",
            "Dajiala Paid Canary",
            (
                "dajiala_paid_wave07_completed_low_roi_success_rate_green"
                if paid_latest_success_green
                else
                "dajiala_paid_wave07_ready_to_run_paid_authorized"
                if dajiala_paid_wave_execution_allowed
                else "dajiala_paid_wave07_prepared_runtime_key_missing_blocked"
                if dajiala_paid_wave_execution_key_missing
                else
                "dajiala_roi_budget_gate_packet_ready_paid_blocked"
                if dajiala_roi_budget_gate_packet_ready
                else "canary_usable_but_paid_waves_blocked"
            ),
            bool(paid_latest_success_green),
            evidence(
                root,
                reports,
                [
                    "dajiala_canary",
                    "dajiala_roi_budget_gate_packet",
                    "dajiala_paid_wave_execution_packet",
                    "dajiala_paid_latest_archive_status",
                ],
            ),
            blockers=list(
                []
                if paid_latest_success_green
                else dajiala_paid_wave_execution_packet.get("blockers")
                if dajiala_paid_wave_execution_packet_ready
                else dajiala_roi_budget_gate_packet.get("hard_gates_remaining")
                if dajiala_roi_budget_gate_packet_ready
                else ["paid batch/waves blocked by account balance" if has_balance_blocker else "paid batch not currently authorized"]
            ),
            next_safe_action=(
                "Use wave07 archive/OCR/vector/entity staging outputs as consumed evidence; do not rerun the same wave."
                if paid_latest_success_green
                else "Run the generated bounded wave07 runner from an environment that already has DAJIALA_API_KEY/JZL_API_KEY; stop on packet stop rules."
                if dajiala_paid_wave_execution_allowed
                else "Inject DAJIALA_API_KEY/JZL_API_KEY into the runtime without writing it to files, then run the generated bounded wave07 runner."
                if dajiala_paid_wave_execution_key_missing
                else
                "Use ROI/budget packet as the paid-wave checklist; do not spend until a fresh cap and downstream-write decision exist."
                if dajiala_roi_budget_gate_packet_ready
                else "Do not spend on further waves until the paid gate is explicitly green."
            ),
            metrics={
                "next_paid_wave_allowed": (
                    dajiala_paid_wave_execution_packet.get("next_paid_wave_allowed")
                    if dajiala_paid_wave_execution_packet_ready
                    else dajiala_roi_budget_gate_packet.get("next_paid_wave_allowed")
                ),
                "paid_api_used": dajiala_roi_budget_gate_packet.get("paid_api_used"),
                "balance_query_executed": dajiala_roi_budget_gate_packet.get("balance_query_executed"),
                "roi_metrics": dajiala_roi_budget_gate_packet.get("roi_metrics"),
                "hard_gates_remaining_count": len(dajiala_roi_budget_gate_packet.get("hard_gates_remaining") or []),
                "paid_wave_selected_rows": dajiala_paid_wave_execution_packet.get("selected_rows"),
                "paid_wave_estimated_cost": dajiala_paid_wave_execution_packet.get("estimated_wave_cost"),
                "paid_wave_runtime_key_present": dajiala_paid_wave_execution_packet.get("runtime_key_present"),
                "paid_wave_authorized": dajiala_paid_wave_execution_packet.get("paid_authorized"),
                "paid_wave_runner_path": dajiala_paid_wave_execution_packet.get("runner_path"),
                "paid_latest_wave": "wave07",
                "paid_latest_archive_completed": paid_latest_completed,
                "paid_latest_total": paid_latest_total,
                "paid_latest_succeeded": paid_latest_succeeded,
                "paid_latest_failed": paid_latest_failed,
                "paid_latest_success_rate": round(paid_latest_success_rate, 4),
            },
        ),
        prd(
            "PRD-07",
            "Production Graph Promotion",
            (
                "graph_production_promotion_verified"
                if graph_production_promotion_verified
                else "graph_promotion_ready_policy_authorized"
                if graph_promotion_allowed
                else "report_complete_blocked_by_production_graph_policy"
                if graph_promotion_report_ready
                else "blocked_by_production_graph_policy"
            ),
            graph_production_promotion_verified,
            evidence(
                root,
                reports,
                [
                    "graph_promotion_readiness",
                    "graph_production_promotion_verify",
                    "neo4j_p1",
                    "cdcr",
                    "cdcr_review",
                    "social_deep_edges",
                    "opencli_social_identity_review",
                    "identity_neo4j_staging_gate_packet",
                ],
            ),
            blockers=list(
                graph_promotion.get("blockers")
                or ([] if graph_promotion_allowed else ["PRODUCTION_GRAPH_LABELS is globally forbidden", "accepted production graph edges are not proven"])
            ),
            next_safe_action=(
                "Keep rollback command available and use production label query smoke as consumer evidence."
                if graph_production_promotion_verified
                else "Run the graph promotion canary/apply lane only after a production-label write command is selected and audited."
                if graph_promotion_allowed
                else "Use readiness report as promotion blocker evidence; real promotion still forbidden."
                if graph_promotion_report_ready
                else "Safe next slice: report-only graph promotion plan/validator without applying labels."
            ),
            metrics={
                "decision": graph_promotion.get("decision"),
                "promotion_allowed": graph_promotion.get("promotion_allowed"),
                "promotion_verified": graph_production_promotion_verified,
                "promotion_verify_decision": graph_production_promotion_verify.get("decision"),
                "promotion_after_counts": graph_production_promotion_verify.get("after_counts"),
                "live_counts": graph_promotion.get("live_counts"),
                "review_inputs": graph_promotion.get("review_inputs"),
            },
        ),
        prd(
            "PRD-08",
            "Consumer Production Deploy",
            (
                "cloudrun_deploy_and_smoke_verified"
                if cloudrun_deploy_verified and cloudrun_production_smoke_ready
                else "cloudrun_deploy_verified"
                if cloudrun_deploy_verified
                else "cloudrun_deploy_blocked_external_cli"
                if cloudrun_deploy_report_ready
                else
                "production_gate_packet_ready_deploy_blocked"
                if consumer_gate_packet_ready
                and consumer_production_policy_blocked
                else "production_gate_packet_ready_endpoint_weekly_blocked"
                if consumer_gate_packet_ready
                and consumer_production_hard_gates
                else "production_gate_packet_ready"
                if consumer_gate_packet_ready
                else "report_complete_blocked_by_production_publish_policy"
                if deploy_readiness_report_ready
                else "blocked_by_production_publish_policy"
            ),
            cloudrun_deploy_verified and cloudrun_production_smoke_ready,
            evidence(
                root,
                reports,
                [
                    "consumer_deploy_readiness",
                    "consumer_publish_gate",
                    "weekly_path",
                    "consumer_production_gate_packet",
                    "cloudrun_deploy_execution",
                    "cloudrun_stage7_production_smoke",
                ],
            ),
            blockers=list(
                []
                if cloudrun_deploy_verified and cloudrun_production_smoke_ready
                else ["cloudrun production smoke is not verified"]
                if cloudrun_deploy_verified and not cloudrun_production_smoke_ready
                else cloudrun_deploy_execution.get("blockers")
                or consumer_production_gate_packet.get("hard_gates_remaining")
                or deploy_readiness.get("blockers")
                or ["cloudrun production deploy is not verified", *publish_blockers]
            ),
            next_safe_action=(
                "Monitor production endpoint and keep rollback/version evidence available."
                if cloudrun_deploy_verified and cloudrun_production_smoke_ready
                else "Run post-deploy smoke and record the verified CloudRun version."
                if cloudrun_deploy_verified
                else "CloudBase CLI deploy path is blocked externally; do not claim production publish until version list or post-deploy smoke changes."
                if cloudrun_deploy_report_ready
                else
                "Use production gate packet as the deploy checklist; real deploy remains a separate production gate."
                if consumer_gate_packet_ready
                else
                "Use readiness report as deploy blocker evidence; real deploy remains forbidden."
                if deploy_readiness_report_ready
                else "Safe next slice: deployment readiness report; do not upload or mutate production SQLite."
            ),
            metrics={
                "decision": deploy_readiness.get("decision"),
                "deploy_allowed": deploy_readiness.get("deploy_allowed"),
                "gates": deploy_readiness.get("gates"),
                "local_ready_gate_count": consumer_production_gate_packet.get("local_ready_gate_count"),
                "hard_gates_remaining_count": len(consumer_production_gate_packet.get("hard_gates_remaining") or []),
                "cloudrun_deploy_decision": cloudrun_deploy_execution.get("decision"),
                "cloudrun_production_smoke_decision": cloudrun_stage7_production_smoke.get("decision"),
                "cloudrun_active_version": nested_get(cloudrun_deploy_execution, ("facts", "active_version")),
                "cloudrun_active_version_updated_time": nested_get(
                    cloudrun_deploy_execution, ("facts", "active_version_updated_time")
                ),
            },
        ),
        prd(
            "PRD-09",
            "Storage Migration",
            "snapshot_phase_complete_current_aliases_protected",
            False,
            evidence(root, reports, ["storage_snapshot"]),
            next_safe_action="Do not move Docker VHDX or delete current collections without a separate owner gate.",
            metrics={
                "legacy_candidate_count": storage_snapshot.get("legacy_candidate_count"),
                "local_snapshot_file_count": storage_snapshot.get("local_snapshot_file_count"),
                "current_aliases_untouched": nested_get(storage_snapshot, ("safety", "current_qwen3_aliases_untouched")),
            },
            writes="snapshot_files_only",
        ),
        prd(
            "PRD-10",
            "mem0 Integration Design",
            (
                "mem0_local_write_read_canary_passed"
                if mem0_local_canary_passed
                else "mem0_write_gate_packet_ready_write_blocked"
                if mem0_write_gate_packet_ready
                else "design_ready_write_blocked"
            ),
            mem0_local_canary_passed and not bool(mem0_write_gate_packet.get("hard_gates_remaining")),
            evidence(root, reports, ["mem0_gate", "mem0_local_canary", "mem0_write_gate_packet"]),
            blockers=(
                list(mem0_write_gate_packet.get("hard_gates_remaining") or [])
                if mem0_local_canary_passed
                else list(mem0_write_gate_packet.get("hard_gates_remaining") or ["MEM0_WRITE is globally forbidden"])
            ),
            next_safe_action=(
                "Use local mem0 write/read canary as PRD-10 completion evidence; consumer personalization tuning remains PRD-17."
                if mem0_local_canary_passed
                else
                "Use write gate packet as PRD-10/17 design evidence; do not write mem0 rows until a separate write gate exists."
                if mem0_write_gate_packet_ready
                else "Keep mem0 as design evidence; no memory writes until a separate write gate exists."
            ),
            metrics={
                "mem0_status": mem0_status,
                "mem0_write_allowed": mem0_write_gate_packet.get("mem0_write_allowed"),
                "local_ready_gate_count": mem0_write_gate_packet.get("local_ready_gate_count"),
                "hard_gates_remaining_count": len(mem0_write_gate_packet.get("hard_gates_remaining") or []),
                "candidate_collection_count": len(mem0_write_gate_packet.get("candidate_collections") or []),
                "downstream_readiness": mem0_write_gate_packet.get("downstream_readiness"),
                "local_canary_decision": mem0_local_canary.get("decision"),
                "local_canary_evidence": mem0_write_gate_packet.get("local_canary_evidence"),
            },
            writes="local_mem0_postgres" if mem0_local_canary_passed else "reports_only",
        ),
        prd(
            "PRD-11",
            "Weekly E2E Pipeline",
            (
                "weekly_production_cloudrun_smoke_verified"
                if cloudrun_weekly_production_smoke_ready and bool(weekly_path.get("production_ready"))
                else "weekly_publish_path_ready_smoke_pending"
                if bool(weekly_path.get("production_ready"))
                else "local_e2e_ready_publish_route_report_only"
            ),
            cloudrun_weekly_production_smoke_ready and bool(weekly_path.get("production_ready")),
            evidence(root, reports, ["weekly_path", "cloudrun_weekly_production_smoke"]),
            blockers=(
                []
                if cloudrun_weekly_production_smoke_ready and bool(weekly_path.get("production_ready"))
                else ["weekly CloudRun production smoke is not verified"]
                if bool(weekly_path.get("production_ready"))
                else [
                    "direct Stage7 consumer pack to weekly_event_published is blocked",
                    "production deploy remains PRD-08",
                ]
            ),
            next_safe_action=(
                "Use the selected weekly recommendation/exporter path and CloudRun weekly smoke as PRD-11 production evidence."
                if cloudrun_weekly_production_smoke_ready and bool(weekly_path.get("production_ready"))
                else "Run the CloudRun weekly production smoke after deploy propagation."
                if bool(weekly_path.get("production_ready"))
                else "Keep weekly publish sourced from the existing weekly recommendation/exporter route."
            ),
            metrics={
                "recommended_path": weekly_path.get("recommended_path"),
                "blocked_paths": weekly_blocked_paths,
                "cloudrun_weekly_smoke_decision": cloudrun_weekly_production_smoke.get("decision"),
                "cloudrun_weekly_smoke_warnings": cloudrun_weekly_production_smoke.get("warnings") or [],
                "cloudrun_weekly_llm_coverage": cloudrun_weekly_production_smoke.get("llm_coverage") or {},
            },
            writes="production_http_smoke_report_only" if cloudrun_weekly_production_smoke_ready else "reports_only",
        ),
        prd(
            "PRD-12",
            "Poster/Image Vectorization",
            (
                "poster_vectors_qdrant_staging_written"
                if poster_vector_staging_written
                else "poster_vector_write_gate_packet_ready_write_blocked"
                if poster_vector_write_gate_packet_ready
                else "official_poster_text_vector_jobs_ready_embedding_write_blocked"
                if verified_poster_text_vector_jobs_ready
                else (
                "official_text_gate_ready_embedding_write_blocked"
                if verified_poster_text_gate_ready
                or poster_text_refresh.get("decision") == "poster_ocr_text_gate_ready_official_index"
                else (
                    "sidecar_text_ready_official_contract_blocked"
                    if poster_text_refresh.get("decision") == "poster_ocr_text_gate_sidecar_ready_official_contract_blocked"
                    else (
                        "report_complete_blocked_missing_real_text"
                        if poster_text_refresh_done
                        else "blocked_by_missing_poster_ocr_text"
                    )
                )
                )
            ),
            False,
            evidence(
                root,
                reports,
                [
                    "poster_preflight",
                    "poster_text_gate_refresh",
                    "dajiala_verified_poster_preflight",
                    "dajiala_verified_poster_text_vector_jobs",
                    "qdrant_poster_staging",
                    "poster_vector_write_gate_packet",
                ],
            ),
            blockers=(
                poster_vector_write_hard_gates
                if poster_vector_write_gate_packet_ready
                else ["poster text vector jobs are packaged; embedding and Qdrant writes remain forbidden by the current run gates"]
                if verified_poster_text_vector_jobs_ready
                else (
                ["embedding and Qdrant writes remain forbidden by the current run gates"]
                if verified_poster_text_gate_ready
                else list(poster_text_refresh.get("blockers") or poster_blockers)
                )
            ),
            next_safe_action=(
                "Use poster Qdrant staging collection and alias as PRD-12 downstream evidence; continue image/VL lane separately."
                if poster_vector_staging_written
                else "Use write gate packet as PRD-12 execution checklist; do not embed/upsert/promote aliases in this run."
                if poster_vector_write_gate_packet_ready
                else "Open a separate embedding/write gate before running the poster text embedding canary."
                if verified_poster_text_vector_jobs_ready
                else (
                "Only run poster text vector canary after a separate embedding/write gate."
                if verified_poster_text_gate_ready
                else (
                "Define/review an official-index bridge for sidecar OCR text before any embedding or Qdrant write."
                if poster_text_refresh.get("decision") == "poster_ocr_text_gate_sidecar_ready_official_contract_blocked"
                else (
                    "Only run poster text vector canary after a separate embedding/write gate."
                    if poster_text_refresh.get("decision") == "poster_ocr_text_gate_ready_official_index"
                    else "Wait for real poster OCR text rows; do not embed article text as poster OCR."
                )
                )
                )
            ),
            metrics={
                "poster_text_gate_decision": (
                    dajiala_verified_poster_preflight.get("decision") or poster_text_refresh.get("decision")
                ),
                "text_vectorization_input_gate_met": verified_poster_text_gate_ready
                or poster_text_refresh.get("text_vectorization_input_gate_met"),
                "candidate_counts": poster_text_refresh.get("candidate_counts"),
                "sidecar_plain_text_nonempty": nested_get(poster_text_refresh, ("sidecar", "plain_text_nonempty")),
                "official_text_ready_rows": verified_text_ready_rows
                or nested_get(poster_text_refresh, ("official_index", "text_ready_rows")),
                "verified_local_image_rows": verified_local_image_rows,
                "verified_poster_text_vector_job_count": verified_poster_job_count,
                "verified_poster_text_vector_collection": dajiala_verified_poster_text_vector_jobs.get("collection"),
                "verified_poster_text_vector_image_exists_count": dajiala_verified_poster_text_vector_jobs.get(
                    "image_exists_count"
                ),
                "poster_vector_write_local_ready_gate_count": poster_vector_write_gate_packet.get(
                    "local_ready_gate_count"
                ),
                "poster_vector_write_hard_gates_remaining_count": len(
                    poster_vector_write_gate_packet.get("hard_gates_remaining") or []
                ),
                "poster_vector_qdrant_read_state": poster_vector_write_gate_packet.get("qdrant_read_state"),
                "poster_vector_staging_evidence": poster_vector_staging_evidence,
            },
            writes="local_qdrant_poster_staging" if poster_vector_staging_written else "reports_only",
        ),
        prd(
            "PRD-13",
            "OCR Entity/Event Data Reflow",
            (
                "ocr_entity_merge_staging_written"
                if ocr_entity_merge_staging_written
                else "ocr_entity_merge_write_gate_packet_ready_write_blocked"
                if ocr_entity_merge_write_gate_packet_ready
                else "official_ocr_entity_merge_plan_ready_write_blocked"
                if verified_entity_ready and verified_merge_ready
                else (
                    "official_ocr_entity_extraction_ready_write_blocked"
                    if verified_entity_ready
                else (
                    "sidecar_dry_run_ready_write_blocked"
                    if sidecar_ready
                else (
                    "report_complete_blocked_by_ocr_reflow_contract_gap"
                    if ocr_reflow_report_ready
                    else "blocked_by_ocr_text_and_write_dependencies"
                )
                )
                )
            ),
            False,
            evidence(
                root,
                reports,
                [
                    "ocr_reflow_readiness",
                    "ocr_entity_extraction",
                    "ocr_entity_merge",
                    "ocr_sidecar_entity_extraction",
                    "ocr_sidecar_entity_merge",
                    "dajiala_verified_ocr_entity_extraction",
                    "dajiala_verified_ocr_entity_merge",
                    "ocr_entity_merge_write_gate_packet",
                    "poster_preflight",
                    "dajiala_verified_poster_preflight",
                    "ocr_v30_coverage",
                ],
            ),
            blockers=(
                list(ocr_entity_merge_write_gate_packet.get("hard_gates_remaining") or [])
                if ocr_entity_merge_write_gate_packet_ready
                else ["Verified OCR entity merge plan is report-only; graph/vector writes remain forbidden"]
                if verified_entity_ready and verified_merge_ready
                else (
                    ["OCR entities are extracted from verified Dajiala OCR index; graph/vector writes remain forbidden"]
                    if verified_entity_ready
                else (
                [
                    "sidecar OCR entities are review-required candidates, not accepted graph facts",
                    "official OCR index contract gap remains",
                    "graph/vector write phases remain forbidden",
                ]
                if sidecar_ready
                else list(
                    ocr_reflow.get("blockers")
                    or ["poster OCR text rows are below gate", "graph/vector write phases remain forbidden"]
                )
                )
                )
            ),
            next_safe_action=(
                "Use OCR entity Neo4j staging nodes as downstream graph evidence; production labels remain PRD-07 controlled."
                if ocr_entity_merge_staging_written
                else "Use write gate packet as PRD-13 execution checklist; no Neo4j apply without a separate write gate."
                if ocr_entity_merge_write_gate_packet_ready
                else "Review the verified merge plan; no Neo4j write without a separate staging graph write gate."
                if verified_entity_ready and verified_merge_ready
                else (
                "Use official-index OCR entity candidates as review input; no graph write without a separate review/write gate."
                if verified_entity_ready
                else (
                "Use sidecar dry-run plan as review input only; no staging graph write without a separate review/write gate."
                if sidecar_ready
                else (
                    "Build report-only sidecar OCR structured-field adapter before any graph write."
                    if ocr_reflow_report_ready
                    else "Only run read-only schema/backfill audit unless real OCR text is recovered."
                )
                )
                )
            ),
            metrics={
                "decision": ocr_reflow.get("decision"),
                "reflow_allowed": ocr_reflow.get("reflow_allowed"),
                "gates": ocr_reflow.get("gates"),
                "sidecar_entity_count": sidecar_entity_count,
                "sidecar_would_merge_entities": sidecar_would_merge,
                "sidecar_decision": sidecar_extraction.get("decision"),
                "verified_entity_count": verified_entity_count,
                "verified_entity_type_counts": dajiala_verified_entity_extraction.get("entity_type_counts"),
                "verified_would_merge_entities": verified_would_merge,
                "verified_merge_decision": dajiala_verified_entity_merge.get("decision"),
                "verified_merge_skipped": dajiala_verified_entity_merge.get("skipped"),
                "ocr_entity_merge_write_local_ready_gate_count": ocr_entity_merge_write_gate_packet.get(
                    "local_ready_gate_count"
                ),
                "ocr_entity_merge_write_hard_gates_remaining_count": len(
                    ocr_entity_merge_write_gate_packet.get("hard_gates_remaining") or []
                ),
                "ocr_entity_merge_neo4j_read_state": ocr_entity_merge_write_gate_packet.get("neo4j_read_state"),
                "ocr_entity_merge_review_evidence": ocr_entity_merge_write_gate_packet.get("review_evidence"),
                "ocr_entity_merge_staging_apply_evidence": ocr_entity_merge_write_gate_packet.get(
                    "staging_apply_evidence"
                ),
            },
            writes="local_neo4j_ocr_staging" if ocr_entity_merge_staging_written else "reports_only",
        ),
        prd(
            "PRD-14",
            "Canonical Entity Resolution",
            (
                "canonical_fuzzy_review_gate_ready_report_only"
                if canonical_fuzzy_review_gate_packet_ready
                else "report_only_canary_ready"
                if canonical_ready
                else "pending_report_only_candidate"
            ),
            False,
            evidence(root, reports, ["canonical_entities", "canonical_fuzzy_review_gate_packet", "graph_rag_answer"]),
            blockers=(
                list(canonical_fuzzy_review_gate_packet.get("blockers") or [])
                if canonical_fuzzy_review_gate_packet_ready
                else ["production graph labels are forbidden", "fuzzy rows require review before any future merge/write"]
            ),
            next_safe_action=(
                "Keep fuzzy canonical merge/write deferred; use exact canonical groups and reviewed candidate packet as report-only evidence."
                if canonical_fuzzy_review_gate_packet_ready
                else
                "Use canonical index/review candidates as report-only evidence; future writes need PRD-07 gate."
                if canonical_ready
                else "Run a report-only canonical entity resolution canary over staging/read-only artifacts."
            ),
            metrics={
                "canonical_exact_groups": canonical_summary.get("canonical_exact_groups"),
                "fuzzy_review_candidates": canonical_summary.get("fuzzy_review_candidates"),
                "decision": canonical_summary.get("decision"),
                "canonical_fuzzy_reviewed_candidates": canonical_fuzzy_review_gate_packet.get("reviewed_candidates"),
                "canonical_fuzzy_accepted_merges": canonical_fuzzy_review_gate_packet.get("accepted_merges"),
                "canonical_fuzzy_deferred_merges": canonical_fuzzy_review_gate_packet.get("deferred_merges"),
                "canonical_fuzzy_future_merge_write_deferred": canonical_fuzzy_review_gate_packet.get(
                    "future_fuzzy_merge_write_deferred"
                ),
            },
        ),
        prd(
            "PRD-15",
            "Dajiala Full Repair Waves",
            (
                "dajiala_paid_wave07_completed_consumed_low_roi"
                if paid_latest_success_green
                else
                "dajiala_paid_wave07_ready_to_run_paid_authorized"
                if dajiala_paid_wave_execution_allowed
                else "dajiala_paid_wave07_prepared_runtime_key_missing_blocked"
                if dajiala_paid_wave_execution_key_missing
                else
                "dajiala_roi_budget_gate_packet_ready_more_paid_blocked"
                if dajiala_roi_budget_gate_packet_ready
                else "bounded_wave01_05_report_ready_more_paid_gated"
                if verified_poster_text_gate_ready
                else "blocked_external_paid_balance"
            ),
            False,
            evidence(
                root,
                reports,
                [
                    "dajiala_canary",
                    "dajiala_roi_budget_gate_packet",
                    "dajiala_paid_wave_execution_packet",
                    "dajiala_paid_latest_archive_status",
                    "ocr_v30_coverage",
                    "dajiala_verified_ocr_index",
                ],
            ),
            blockers=(
                []
                if paid_latest_success_green
                else list(dajiala_paid_wave_execution_packet.get("blockers") or [])
                if dajiala_paid_wave_execution_packet_ready
                else list(dajiala_roi_budget_gate_packet.get("hard_gates_remaining") or [])
                if dajiala_roi_budget_gate_packet_ready
                else ["Further paid waves require a fresh ROI/budget gate; wave01-04 evidence is already report-ready"]
                if verified_poster_text_gate_ready
                else ["Dajiala wave029 account balance blocker" if has_balance_blocker else "paid batch gate not green"]
            ),
            next_safe_action=(
                "Wave07 is consumed through OCR index, Qdrant poster staging, and Neo4j OCR staging; require a fresh ROI cap before any wave08."
                if paid_latest_success_green
                else "Run bounded wave07 with the generated runner, then immediately inspect archive status/results and stop on packet stop rules."
                if dajiala_paid_wave_execution_allowed
                else "Runtime key is missing; keep wave07 queue/runner prepared and continue non-paid gates until the key exists in the process environment."
                if dajiala_paid_wave_execution_key_missing
                else
                "Do not buy another wave until ROI/budget packet gates are explicitly resolved."
                if dajiala_roi_budget_gate_packet_ready
                else "Do not buy another wave until downstream PRD-12/13 consumes the verified OCR rows."
                if verified_poster_text_gate_ready
                else "Do not continue paid waves; use non-paid recoverability audits only."
            ),
            metrics={
                "verified_dajiala_ocr_rows": int(dajiala_verified_index.get("record_count") or 0),
                "verified_existing_local_image_rows": (dajiala_verified_index.get("asset_counts") or {}).get(
                    "existing_local_image_gt0"
                ),
                "next_paid_wave_allowed": dajiala_roi_budget_gate_packet.get("next_paid_wave_allowed"),
                "paid_wave_next_paid_wave_allowed": dajiala_paid_wave_execution_packet.get("next_paid_wave_allowed"),
                "paid_wave_selected_rows": dajiala_paid_wave_execution_packet.get("selected_rows"),
                "paid_wave_estimated_cost": dajiala_paid_wave_execution_packet.get("estimated_wave_cost"),
                "paid_wave_runtime_key_present": dajiala_paid_wave_execution_packet.get("runtime_key_present"),
                "paid_wave_authorized": dajiala_paid_wave_execution_packet.get("paid_authorized"),
                "paid_latest_wave": "wave07",
                "paid_latest_archive_completed": paid_latest_completed,
                "paid_latest_total": paid_latest_total,
                "paid_latest_succeeded": paid_latest_succeeded,
                "paid_latest_failed": paid_latest_failed,
                "paid_latest_success_rate": round(paid_latest_success_rate, 4),
                "estimated_all_remaining_request_cost": nested_get(
                    dajiala_roi_budget_gate_packet,
                    ("roi_metrics", "estimated_all_remaining_request_cost_from_canary_unit_cost"),
                ),
                "hard_gates_remaining_count": len(dajiala_roi_budget_gate_packet.get("hard_gates_remaining") or []),
            },
        ),
        prd(
            "PRD-16",
            "Social Platform Deep Integration",
            (
                "identity_neo4j_staging_canary_written"
                if identity_neo4j_staging_gate_packet_ready
                and strict_prd16_accepted_edges > 0
                and identity_neo4j_staging_canary_executed
                else "identity_neo4j_staging_gate_packet_ready_write_authorized"
                if identity_neo4j_staging_gate_packet_ready
                and strict_prd16_accepted_edges > 0
                and identity_neo4j_staging_authorized
                and not identity_neo4j_staging_hard_gates
                else "identity_neo4j_staging_gate_packet_ready_write_blocked"
                if identity_neo4j_staging_gate_packet_ready
                and strict_prd16_accepted_edges > 0
                else "identity_acceptance_gate_packet_ready_write_blocked"
                if social_identity_acceptance_gate_packet_ready
                and strict_prd16_accepted_edges == 0
                else "identity_acceptance_gate_packet_strict_edges_ready_write_blocked"
                if social_identity_acceptance_gate_packet_ready
                else "opencli_identity_review_ready_write_blocked"
                if opencli_identity_review_done
                else (
                "identity_cross_evidence_review_ready_write_blocked"
                if social_identity_review_done
                else "report_complete_identity_review_blocked"
                )
            ),
            False,
            evidence(
                root,
                reports,
                [
                    "social_deep_edges",
                    "social_identity_review",
                    "opencli_social_profile_evidence",
                    "opencli_social_identity_review",
                    "social_identity_acceptance_gate_packet",
                    "identity_neo4j_staging_gate_packet",
                ],
            ),
            blockers=list(
                identity_neo4j_staging_hard_gates
                if identity_neo4j_staging_gate_packet_ready
                else social_identity_acceptance_gate_packet.get("hard_gates_remaining")
                if social_identity_acceptance_gate_packet_ready
                else (
                    opencli_identity_review.get("blockers")
                    if opencli_identity_review_done
                    else social_identity_review.get("blockers")
                )
                or ["public reachability alone is not identity proof"]
            ),
            next_safe_action=(
                "Verify the Neo4j staging canary report; production labels remain PRD-07 controlled."
                if identity_neo4j_staging_gate_packet_ready
                and identity_neo4j_staging_canary_executed
                else "Run the generated Neo4j staging canary command; do not promote production labels until the canary verifies."
                if identity_neo4j_staging_gate_packet_ready
                and identity_neo4j_staging_authorized
                and not identity_neo4j_staging_hard_gates
                else "Use identity Neo4j staging gate packet as report-only write readiness evidence."
                if identity_neo4j_staging_gate_packet_ready
                else "Use acceptance gate packet for source-backed row review; keep accepted social edges empty until specific rows pass."
                if social_identity_acceptance_gate_packet_ready
                else "Use strong OpenCLI review candidates for source-backed acceptance review; keep accepted edges empty until that gate exists."
                if opencli_identity_review_done
                else (
                "Review strong/medium identity candidates under a stricter source-backed contract; keep accepted edges empty."
                if social_identity_review_done
                else "Add identity cross-evidence before any staging write beyond reviewed accepted edges."
                )
            ),
            metrics={
                "candidate_edges_seen": social_identity_review.get("candidate_edges_seen"),
                "strong_review_candidates": social_identity_review.get("strong_review_candidates"),
                "medium_review_candidates": social_identity_review.get("medium_review_candidates"),
                "accepted_edges_after_review": social_identity_review.get("accepted_edges"),
                "opencli_evidence_rows": opencli_identity_review.get("opencli_evidence_rows"),
                "opencli_matched_identity_rows": opencli_identity_review.get("matched_identity_rows"),
                "strong_opencli_review_candidates": opencli_identity_review.get("strong_opencli_review_candidates"),
                "medium_opencli_review_candidates": opencli_identity_review.get("medium_opencli_review_candidates"),
                "accepted_edges_after_opencli_review": opencli_identity_review.get("accepted_edges"),
                "identity_acceptance_gate_candidates": social_identity_acceptance_gate_packet.get(
                    "review_candidates_total"
                ),
                "identity_acceptance_gate_accepted_edges": social_identity_acceptance_gate_packet.get(
                    "accepted_edges_total"
                ),
                "identity_acceptance_gate_accepted_edges_by_scope": social_identity_accepted_edges_by_scope,
                "identity_acceptance_gate_hard_gates_remaining_count": len(
                    social_identity_acceptance_gate_packet.get("hard_gates_remaining") or []
                ),
                "identity_neo4j_staging_writer_valid_edges": identity_neo4j_staging_gate_packet.get(
                    "writer_valid_edges"
                ),
                "identity_neo4j_staging_manifest_path": identity_neo4j_staging_gate_packet.get("manifest_path"),
                "identity_neo4j_staging_local_ready_gate_count": identity_neo4j_staging_gate_packet.get(
                    "local_ready_gate_count"
                ),
            },
        ),
        prd(
            "PRD-17",
            "Weekly Recommendation Engine",
            "report_only_canaries_ready_without_mem0",
            False,
            evidence(root, reports, ["hybrid_recommend", "mem0_gate"]),
            blockers=["mem0 personalization disabled", "real recency limited by missing source-backed time_iso"],
            next_safe_action="Use graph/trending/hybrid as staging signals; defer mem0/reranker writes.",
        ),
        prd(
            "PRD-18",
            "Hermes Pipeline Monitor",
            "report_only_monitor_ready_amber",
            False,
            evidence(root, reports, ["hermes_alerts"]),
            blockers=["known amber alerts remain by design"],
            next_safe_action="Keep monitor in report-only mode; alerts track known blockers.",
        ),
        prd(
            "PRD-19",
            "Graph RAG / LLM Query Enhancement",
            "read_only_answer_drafts_ready_without_llm",
            False,
            evidence(root, reports, ["graph_rag_answer"]),
            blockers=["LLM answer canary requires separate model/paid gate", "production writes forbidden"],
            next_safe_action="Use deterministic drafts/citations as a read-only base; no LLM/vector writes.",
        ),
    ]

    # Drop empty blocker strings caused by conditional evidence.
    for item in prds:
        item["blockers"] = [text for text in item["blockers"] if text]

    missing_artifacts = sorted(
        {
            ev["path"]
            for item in prds
            for ev in item["evidence"]
            if not ev.get("exists")
        }
    )
    status_counts = Counter(item["status"] for item in prds)
    blocked_prds = [
        item["id"]
        for item in prds
        if item["status"].startswith("blocked") or "blocked" in item["status"]
    ]
    next_safe = []
    if not canonical_ready:
        next_safe.append(
            {
                "id": "PRD-14",
                "action": "Run report-only canonical entity resolution canary.",
                "why": "It can improve graph quality evidence without production graph labels or paid APIs.",
            }
        )
    if not graph_promotion_report_ready:
        next_safe.append(
            {
                "id": "PRD-07",
                "action": "Build report-only graph promotion validator.",
                "why": "Promotion itself is forbidden, but a validator can surface exact remaining blockers.",
            }
        )
    if not deploy_readiness_report_ready:
        next_safe.append(
            {
                "id": "PRD-08",
                "action": "Build report-only production deploy readiness report.",
                "why": "Deploy is forbidden, but readiness gaps can be audited without writes.",
            }
        )
    if not sidecar_ready:
        next_safe.append(
            (
                {
                    "id": "PRD-13",
                    "action": "Build report-only sidecar OCR structured-field adapter.",
                    "why": "Sidecar OCR outputs exist but are outside the official OCR index contract.",
                }
                if ocr_reflow_report_ready
                else {
                    "id": "PRD-13",
                    "action": "Run read-only OCR entity/event reflow audit.",
                    "why": "Write phases are blocked, but a schema/backfill audit can close the remaining evidence gap.",
                }
            )
        )
    if not poster_text_refresh_done:
        next_safe.append(
            {
                "id": "PRD-12",
                "action": "Refresh poster OCR text gate from real OCR index and sidecar evidence without embeddings.",
                "why": "Vectorization remains blocked, but the text gate can be rechecked without graph/vector writes.",
            }
        )
    elif not social_identity_review_done:
        next_safe.append(
            {
                "id": "PRD-16",
                "action": "Run report-only identity cross-evidence audit for social deep candidates.",
                "why": "PRD-16 has reachable public candidates but 0 accepted identity-proven edges.",
            }
        )
    elif not ocr_asset_synthesis_done:
        next_safe.append(
            {
                "id": "PRD-05a",
                "action": "Synthesize remaining OCR asset-source blockers and non-paid unblock options.",
                "why": "Paid Dajiala waves are blocked and the remaining OCR/vector gates depend on source-backed image contracts.",
            }
        )
    else:
        next_safe.append(
            {
                "id": "FINAL",
                "action": "Build final full-pipeline readiness gate from all PRD blocker evidence.",
                "why": "All PRD blockers are explicit; the final gate can choose production-ready, staging-ready, or report-only.",
            }
        )

    executed_writes = []
    if poster_vector_staging_written:
        executed_writes.append("local_qdrant_poster_staging")
    if ocr_entity_merge_staging_written:
        executed_writes.append("local_neo4j_ocr_staging")
    if mem0_local_canary_passed:
        executed_writes.append("local_mem0_postgres")
    if paid_latest_completed:
        executed_writes.append("paid_dajiala_wave07_archive_reports")

    weekly_production_ready = bool(weekly_path.get("production_ready"))
    consumer_deploy_allowed = bool(deploy_readiness.get("deploy_allowed"))
    consumer_production_gate_clear = consumer_gate_packet_ready and not consumer_production_hard_gates
    consumer_publish_allowed = bool(consumer_gate.get("publish_allowed"))
    release_ready_gates = {
        "status_artifacts_present": not missing_artifacts,
        "no_blocked_prds": not blocked_prds,
        "consumer_publish_allowed": consumer_publish_allowed,
        "consumer_production_gate_clear": consumer_production_gate_clear,
        "consumer_deploy_allowed": consumer_deploy_allowed,
        "cloudrun_deploy_verified": cloudrun_deploy_verified,
        "cloudrun_production_smoke_ready": cloudrun_production_smoke_ready,
        "cloudrun_weekly_production_smoke_ready": cloudrun_weekly_production_smoke_ready,
        "graph_promotion_allowed": graph_promotion_allowed,
        "graph_production_promotion_verified": graph_production_promotion_verified,
        "weekly_production_ready": weekly_production_ready,
        "poster_vectors_qdrant_staging_written": poster_vector_staging_written,
        "ocr_entity_merge_staging_written": ocr_entity_merge_staging_written,
        "mem0_local_write_read_canary_passed": mem0_local_canary_passed,
        "dajiala_wave07_success_green": paid_latest_success_green,
    }
    global_blockers = []
    if missing_artifacts:
        global_blockers.append("required status artifacts are missing")
    if blocked_prds:
        global_blockers.append("one or more PRD statuses are still blocked")
    if not consumer_publish_allowed:
        global_blockers.append("consumer production publish gate is blocked")
    if not consumer_production_gate_clear:
        global_blockers.extend(consumer_production_hard_gates or ["consumer production gate packet is not clear"])
    if not graph_promotion_allowed:
        global_blockers.extend(graph_promotion.get("blockers") or ["graph promotion readiness is not allowed"])
    if not weekly_production_ready:
        global_blockers.append("weekly publish path is not production-ready")
    if not cloudrun_deploy_verified:
        global_blockers.append("CloudRun production deploy is not verified")
    if not poster_vector_staging_written:
        global_blockers.append("poster text vectors are not written to Qdrant staging")
    if not ocr_entity_merge_staging_written:
        global_blockers.append("OCR entities are not written to Neo4j staging")
    if not mem0_local_canary_passed:
        global_blockers.append("mem0 local write/read canary is not passed")
    if not paid_latest_success_green and not dajiala_paid_wave_execution_allowed:
        global_blockers.append("paid Dajiala waves are blocked by external balance/gate")
    elif not paid_latest_success_green:
        global_blockers.append("Dajiala wave07 has not completed with an acceptable success rate")
    global_blockers = list(dict.fromkeys(str(item) for item in global_blockers if item))

    known_limitations = []
    if weekly_path.get("blocked_paths"):
        known_limitations.append("direct Stage7 consumer pack to weekly_event_published remains blocked; release path uses weekly recommendation/exporter")
    if ocr_missing:
        known_limitations.append(f"fixed-route OCR missing count remains {ocr_missing}; PRD-05a stopped HTTP expansion on low ROI")
    if not non_dajiala_image_evidence:
        known_limitations.append("non-Dajiala remaining lane still has no independent image evidence")
    if paid_latest_failed:
        known_limitations.append(f"Dajiala wave07 rejected or failed rows: {paid_latest_failed}")
    if cloudrun_deploy_report_ready and not cloudrun_deploy_verified:
        known_limitations.append("CloudRun deploy attempt is blocked by external CloudBase CLI/no visible version update")
    if cloudrun_deploy_verified and not cloudrun_production_smoke_ready:
        known_limitations.append("CloudRun deploy is verified but production Stage7 HTTP smoke is missing or failed")
    if bool(weekly_path.get("production_ready")) and not cloudrun_weekly_production_smoke_ready:
        known_limitations.append("weekly publish path is production-ready but CloudRun weekly smoke is missing or failed")

    production_ready = all(release_ready_gates.values())
    release_decision = (
        "production_ready"
        if production_ready
        else "staging_ready_release_blocked_by_business_policy"
        if not blocked_prds and consumer_deploy_allowed and graph_promotion_allowed
        else "staging_ready_release_blocked_by_external_paid_gate"
        if not blocked_prds and any("Dajiala" in item for item in global_blockers)
        else "report_only_complete_not_releasable"
    )
    safety = [
        "status refresh does not execute production publish",
        "status refresh does not write production SQLite",
        "status refresh does not apply production graph labels",
        "Qdrant and Neo4j writes are limited to explicit local staging reports",
        "no additional paid API call during status refresh" if paid_latest_completed else "no paid API call",
        "no D: scan",
    ]
    safety.append(
        "mem0 writes limited to local stage7_memories canary"
        if mem0_local_canary_passed
        else "no mem0 write"
    )

    return {
        "schema_version": "stage7_prd_longrun_status.v1",
        "generated_at": now_iso(),
        "ok": not missing_artifacts,
        "report_only": True,
        "production_ready": production_ready,
        "release_decision": release_decision,
        "workspace": str(root),
        "longrun_state_present": longrun_path.exists(),
        "global_blockers": global_blockers,
        "known_limitations": known_limitations,
        "release_ready_gates": release_ready_gates,
        "summary": {
            "total_prds": len(prds),
            "status_counts": dict(sorted(status_counts.items())),
            "blocked_prds": blocked_prds,
            "missing_artifacts": missing_artifacts,
            "stable_unique": stable_unique,
            "fixed_route_missing": ocr_missing,
            "non_dajiala_remaining_has_image_evidence": non_dajiala_image_evidence,
            "weekly_recommended_path": weekly_path.get("recommended_path"),
            "consumer_publish_allowed": consumer_publish_allowed,
            "consumer_deploy_allowed": consumer_deploy_allowed,
            "cloudrun_deploy_verified": cloudrun_deploy_verified,
            "cloudrun_production_smoke_ready": cloudrun_production_smoke_ready,
            "cloudrun_weekly_production_smoke_ready": cloudrun_weekly_production_smoke_ready,
            "graph_promotion_allowed": graph_promotion_allowed,
            "graph_production_promotion_verified": graph_production_promotion_verified,
            "weekly_production_ready": weekly_production_ready,
            "mem0_write_allowed": mem0_write_gate_packet.get("mem0_write_allowed"),
        },
        "next_safe_iterations": next_safe,
        "prds": prds,
        "safety": safety,
        "writes": executed_writes or "reports_only",
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage7 PRD Longrun Status",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- production_ready: `{report['production_ready']}`",
        f"- release_decision: `{report.get('release_decision')}`",
        f"- workspace: `{report['workspace']}`",
        "",
        "## Summary",
        "",
    ]
    summary = report["summary"]
    for key in (
        "total_prds",
        "stable_unique",
        "fixed_route_missing",
        "non_dajiala_remaining_has_image_evidence",
        "weekly_recommended_path",
        "consumer_publish_allowed",
        "consumer_deploy_allowed",
        "graph_promotion_allowed",
        "weekly_production_ready",
        "mem0_write_allowed",
    ):
        lines.append(f"- {key}: `{summary.get(key)}`")
    lines.extend(["", "## Global Blockers", ""])
    if report["global_blockers"]:
        for blocker in report["global_blockers"]:
            lines.append(f"- {blocker}")
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
    lines.extend(["", "## Next Safe Iterations", ""])
    for item in report["next_safe_iterations"]:
        lines.append(f"- `{item['id']}`: {item['action']} ({item['why']})")
    lines.extend(["", "## PRD Scoreboard", ""])
    lines.append("| PRD | Status | Production Ready | Blockers | Next Safe Action |")
    lines.append("|---|---|---:|---|---|")
    for item in report["prds"]:
        blockers = "; ".join(item["blockers"]) if item["blockers"] else "none"
        lines.append(
            f"| {item['id']} | `{item['status']}` | `{item['production_ready']}` | {blockers} | {item['next_safe_action']} |"
        )
    lines.extend(["", "## Missing Artifacts", ""])
    missing = report["summary"]["missing_artifacts"]
    if missing:
        for rel in missing:
            lines.append(f"- `{rel}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Safety", ""])
    for item in report["safety"]:
        lines.append(f"- {item}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    report = build_status(root)
    out_dir = root / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "prd_longrun_status.json", report)
    write_markdown(out_dir / "prd_longrun_status.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "production_ready": report["production_ready"],
                "total_prds": report["summary"]["total_prds"],
                "blocked_prds": report["summary"]["blocked_prds"],
                "report": str(out_dir / "prd_longrun_status.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] or args.report_only_exit_zero else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
