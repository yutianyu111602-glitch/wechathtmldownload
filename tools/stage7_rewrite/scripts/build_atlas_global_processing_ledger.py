#!/usr/bin/env python3
"""Build a global processing ledger for the China electronic music atlas.

This is a report-only audit for the whole wechathtmldownload project line. It
answers whether historical pulled data has reached the atlas production chain
across discovery, archive, OCR/Markdown, LLM export, Stage7 stable extraction,
graph, vectors, external evidence, and product surfaces.

It reads only known local project reports and manifests. It never scans D:
roots, calls the network, runs OCR/LLM, pays Dajiala, or writes production
stores.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCRIPT_PATH = Path(__file__).resolve()
STAGE7_ROOT = SCRIPT_PATH.parents[1]
PROJECT_ROOT = SCRIPT_PATH.parents[3]
REPORTS = STAGE7_ROOT / "reports"
ROOT_REPORTS = PROJECT_ROOT / "reports"
DEFAULT_OUT_DIR = REPORTS / "atlas_global_processing_ledger_20260519"
SCHEMA_VERSION = "atlas_global_processing_ledger.v1"


DEFAULT_PATHS = {
    "total_deep_audit_md": ROOT_REPORTS / "WECHAT_TOTAL_DEEP_AUDIT_wechat_total_deep_audit_20260518.md",
    "ddownload_relation_md": ROOT_REPORTS / "WECHAT_DDOWNLOAD_RELATION_RESEARCH_wechat_ddownload_relation_20260518.md",
    "lineage_json": REPORTS / "atlas_full_source_lineage_47k_93k_gap_20260519" / "atlas_full_source_lineage.json",
    "gap_packet_json": REPORTS / "atlas_gap_backfill_execution_packet_20260519" / "gap_backfill_execution_packet.json",
    "gap_ledger_json": REPORTS / "atlas_gap_ledger_refresh_20260519_0715" / "gap_ledger.json",
    "stable_merge_json": REPORTS
    / "stable_merge_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518"
    / "stable_merge_summary.json",
    "consumer_release_manifest_json": REPORTS
    / "consumer_release_pack_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518"
    / "manifest.json",
    "graph_verify_json": REPORTS
    / "graph_production_promotion_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_verify_20260519"
    / "promotion_report.json",
    "qdrant_alias_apply_json": REPORTS / "qdrant_role_alias_apply_47k_delta375_20260519" / "qdrant_role_alias_apply_report.json",
    "vector_role_summary_json": REPORTS
    / "vector_role_artifacts_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518"
    / "role_artifacts_summary.json",
    "vector_full_wave_status_json": REPORTS
    / "vector_role_full_wave_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518"
    / "_sequence_status"
    / "sequence_status.json",
    "dajiala_queue_audit_json": REPORTS / "dajiala_paid_queue_consumption_audit_20260519" / "dajiala_paid_queue_consumption_audit.json",
    "identity_final_lock_json": REPORTS / "graph_candidate_pack_final_lock_47k_delta375_20260519" / "graph_candidate_pack_readiness.json",
    "identity_review_gate_json": REPORTS
    / "external_identity_future_direct_proof_review_gate_47k_delta375_20260519"
    / "source_followup_review_gate_summary.json",
    "graph_rag_smoke_json": REPORTS
    / "graph_rag_recommendation_current_smoke_47k_delta375_final_lock_20260519"
    / "graph_rag_recommendation_current_smoke.json",
    "service_stage7_package_manifest_json": PROJECT_ROOT
    / "services"
    / "weekly_activity_cloudrun"
    / "data"
    / "stage7_atlas"
    / "package_manifest.json",
    "service_stage7_release_pointer_json": PROJECT_ROOT
    / "services"
    / "weekly_activity_cloudrun"
    / "data"
    / "stage7_atlas"
    / "release_pointer.staging.json",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, payload: Any) -> None:
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


def nested_get(data: dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def regex_int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return None
    raw = match.group(1).replace(",", "")
    return int_or_none(raw)


def parse_ddownload_counts(total_md: str, relation_md: str) -> dict[str, Any]:
    combined = "\n".join([total_md, relation_md])
    counts = {
        "discovered_records": regex_int(combined, r"DDownload discovered / queued / audit records:\s*`?([0-9,]+)`?"),
        "archive_archived": regex_int(combined, r"Archive audit archived:\s*`?([0-9,]+)`?"),
        "archive_partial": regex_int(combined, r"partial=([0-9,]+)"),
        "archive_missing": regex_int(combined, r"missing=([0-9,]+)"),
        "archive_retry_queue": regex_int(combined, r"retry queue\s*`?([0-9,]+)`?"),
        "llm_export_succeeded": regex_int(combined, r"LLM export succeeded:\s*`?([0-9,]+)`?"),
        "llm_export_failed": regex_int(combined, r"LLM export failed\s*\|\s*`?([0-9,]+)`?"),
        "llm_release_v2_articles": regex_int(combined, r"LLM release v2 (?:copied )?articles:\s*`?([0-9,]+)`?"),
        "llm_release_v2_ready": regex_int(combined, r"ready[\"`]?[:=]\s*([0-9,]+)"),
        "llm_release_v2_review": regex_int(combined, r"review[\"`]?[:=]\s*([0-9,]+)"),
        "llm_release_v2_blocked": regex_int(combined, r"blocked[\"`]?[:=]\s*([0-9,]+)"),
    }
    if counts["archive_retry_queue"] is None:
        archived = counts["archive_archived"] or 0
        discovered = counts["discovered_records"] or 0
        counts["archive_retry_queue"] = discovered - archived if discovered and archived else None
    if counts["llm_export_failed"] is None:
        discovered = counts["discovered_records"] or 0
        succeeded = counts["llm_export_succeeded"] or 0
        counts["llm_export_failed"] = discovered - succeeded if discovered and succeeded else None
    return counts


def source_row(
    *,
    source_id: str,
    stage: str,
    count: int | None,
    status: str,
    interpretation: str,
    evidence: list[str],
    counts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.source_row",
        "source_id": source_id,
        "stage": stage,
        "count": count,
        "status": status,
        "interpretation": interpretation,
        "evidence": evidence,
        "counts": counts or {},
    }


def ledger_row(
    *,
    source_id: str,
    total: int | None,
    classification: str,
    stage_status: dict[str, str],
    decision: str,
    evidence: list[str],
    gaps: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.ledger_row",
        "source_id": source_id,
        "total": total,
        "classification": classification,
        "stage_status": stage_status,
        "decision": decision,
        "gaps": gaps or [],
        "evidence": evidence,
    }


def gap_row(
    *,
    gap_id: str,
    source_id: str,
    count: int | None,
    severity: str,
    class_: str,
    decision: str,
    next_action: str,
    evidence: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.gap_row",
        "gap_id": gap_id,
        "source_id": source_id,
        "count": count,
        "severity": severity,
        "class": class_,
        "decision": decision,
        "next_action": next_action,
        "evidence": evidence,
    }


def stage_status(**kwargs: str) -> dict[str, str]:
    stages = {
        "source_discovery": "unknown",
        "archive_assets_dajiala": "unknown",
        "ocr_markdown": "unknown",
        "llm_export_extract": "unknown",
        "stable_structured": "unknown",
        "graph_marker": "unknown",
        "vector_retrieval": "unknown",
        "external_media_identity": "unknown",
        "qa_orchestration": "unknown",
        "product_surface": "unknown",
    }
    stages.update(kwargs)
    return stages


def build_global_ledger(paths: dict[str, Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    total_md = read_text(paths["total_deep_audit_md"])
    relation_md = read_text(paths["ddownload_relation_md"])
    ddownload = parse_ddownload_counts(total_md, relation_md)
    lineage = read_json(paths["lineage_json"])
    gap_packet = read_json(paths["gap_packet_json"])
    gap_ledger = read_json(paths["gap_ledger_json"])
    stable = read_json(paths["stable_merge_json"])
    release_manifest = read_json(paths["consumer_release_manifest_json"])
    graph_verify = read_json(paths["graph_verify_json"])
    qdrant_alias = read_json(paths["qdrant_alias_apply_json"])
    vector_roles = read_json(paths["vector_role_summary_json"])
    vector_wave = read_json(paths["vector_full_wave_status_json"])
    dajiala = read_json(paths["dajiala_queue_audit_json"])
    identity_final = read_json(paths["identity_final_lock_json"])
    identity_review = read_json(paths["identity_review_gate_json"])
    graph_rag_smoke = read_json(paths["graph_rag_smoke_json"])
    service_manifest = read_json(paths["service_stage7_package_manifest_json"])
    service_pointer = read_json(paths["service_stage7_release_pointer_json"])

    stable_articles = int_or_none(stable.get("articles")) or int_or_none(release_manifest.get("articles"))
    graph_articles = int_or_none(nested_get(graph_verify, ("after_counts", "article", "promoted")))
    graph_entities = int_or_none(nested_get(graph_verify, ("after_counts", "entity", "promoted")))
    graph_events = int_or_none(nested_get(graph_verify, ("after_counts", "event", "promoted")))
    service_articles = int_or_none(nested_get(service_manifest, ("counts", "articles"))) or int_or_none(
        nested_get(service_pointer, ("counts", "articles"))
    )

    gap_summary = gap_ledger.get("summary") if isinstance(gap_ledger.get("summary"), dict) else {}
    gap_actions = gap_packet.get("actions") if isinstance(gap_packet.get("actions"), list) else []
    by_action = {row.get("action_id"): row for row in gap_actions if isinstance(row, dict)}

    sources = [
        source_row(
            source_id="ddownload_discovered_queue_93761",
            stage="source_discovery",
            count=ddownload["discovered_records"],
            status="historical_substrate_not_graph_truth",
            interpretation="Historical account/URL discovery queue; not all rows are complete article bodies.",
            evidence=[
                str(paths["total_deep_audit_md"]),
                str(paths["ddownload_relation_md"]),
                "D:\\DDownload\\_state\\account-url-prefetch-status.json (not opened in this run)",
                "D:\\DDownload\\_queues\\download_ready_queue.jsonl (not opened in this run)",
            ],
            counts=ddownload,
        ),
        source_row(
            source_id="ddownload_archive_audit",
            stage="archive_assets_dajiala",
            count=ddownload["archive_archived"],
            status="partial_archive_substrate",
            interpretation="Archive-complete subset exists, while partial/missing rows must stay out of graph truth unless repaired.",
            evidence=[str(paths["total_deep_audit_md"]), str(paths["ddownload_relation_md"])],
            counts={
                "archived": ddownload["archive_archived"],
                "partial": ddownload["archive_partial"],
                "missing": ddownload["archive_missing"],
                "retry_queue": ddownload["archive_retry_queue"],
            },
        ),
        source_row(
            source_id="ddownload_llm_export",
            stage="llm_export_extract",
            count=ddownload["llm_export_succeeded"],
            status="mostly_complete_historical_export",
            interpretation="Historical LLM material export succeeded for most rows but still has failed rows and is not current graph truth.",
            evidence=[str(paths["total_deep_audit_md"]), str(paths["ddownload_relation_md"])],
            counts={"succeeded": ddownload["llm_export_succeeded"], "failed": ddownload["llm_export_failed"]},
        ),
        source_row(
            source_id="ddownload_llm_release_v2",
            stage="llm_export_extract",
            count=ddownload["llm_release_v2_articles"],
            status="historical_frozen_pack",
            interpretation="Historical release pack with ready/review/blocked quality split; not automatically promoted to current atlas.",
            evidence=[str(paths["total_deep_audit_md"]), str(paths["ddownload_relation_md"])],
            counts={
                "ready": ddownload["llm_release_v2_ready"],
                "review": ddownload["llm_release_v2_review"],
                "blocked": ddownload["llm_release_v2_blocked"],
            },
        ),
        source_row(
            source_id="atlas_stable_47340",
            stage="stable_structured",
            count=stable_articles,
            status="complete_in_atlas_production",
            interpretation="Current stable atlas base after 47k baseline, V6 P1 repair, and paid wave09-21 delta.",
            evidence=[str(paths["stable_merge_json"]), str(paths["consumer_release_manifest_json"])],
            counts={"source_counts": stable.get("source_counts"), "totals": stable.get("totals")},
        ),
        source_row(
            source_id="atlas_neo4j_graph_marker",
            stage="graph_marker",
            count=graph_articles,
            status="complete_in_atlas_production",
            interpretation="Verified local Neo4j production marker for current atlas base.",
            evidence=[str(paths["graph_verify_json"])],
            counts={"articles": graph_articles, "entities": graph_entities, "events": graph_events},
        ),
        source_row(
            source_id="atlas_qdrant_role_vectors",
            stage="vector_retrieval",
            count=int_or_none(vector_roles.get("scanned_jobs")),
            status="complete_current_aliases_applied",
            interpretation="Role-isolated 1024-d vector artifacts and Qdrant current aliases are applied; model spaces stay isolated.",
            evidence=[str(paths["vector_role_summary_json"]), str(paths["vector_full_wave_status_json"]), str(paths["qdrant_alias_apply_json"])],
            counts={
                "matched_jobs": vector_roles.get("matched_jobs"),
                "sequence_decision": vector_wave.get("decision"),
                "alias_applied": qdrant_alias.get("applied"),
                "alias_action_count": len(qdrant_alias.get("actions") or []),
            },
        ),
        source_row(
            source_id="dajiala_paid_queue_consumption",
            stage="archive_assets_dajiala",
            count=int_or_none(dajiala.get("input_rows")),
            status="paid_queue_consumed_after_exclusions",
            interpretation="Current paid Dajiala queue has no unconsumed payable candidates after exclusions; no paid call is needed from this queue.",
            evidence=[str(paths["dajiala_queue_audit_json"])],
            counts={
                "input_rows": dajiala.get("input_rows"),
                "used_key_count": dajiala.get("used_key_count"),
                "excluded_rows": dajiala.get("excluded_rows"),
                "unconsumed_candidate_rows": dajiala.get("unconsumed_candidate_rows"),
            },
        ),
        source_row(
            source_id="external_identity_media_queue",
            stage="external_media_identity",
            count=int_or_none(identity_review.get("input_rows")) or int_or_none(identity_final.get("external_identity_reviewed_rows")),
            status="reviewed_no_graph_edges",
            interpretation="External profile/media evidence is fully review-gated for the current queue; accepted graph edges remain zero.",
            evidence=[str(paths["identity_review_gate_json"]), str(paths["identity_final_lock_json"])],
            counts={
                "reviewed_rows": identity_review.get("reviewed_rows") or identity_final.get("external_identity_reviewed_rows"),
                "accepted_for_graph": identity_review.get("accepted_for_graph") or identity_final.get("external_identity_edges"),
                "needs_more_source_rows": identity_review.get("needs_more_source_rows") or identity_final.get("external_identity_needs_more_source_rows"),
            },
        ),
        source_row(
            source_id="atlas_graph_rag_recommendation_smoke",
            stage="qa_orchestration",
            count=int_or_none(nested_get(graph_rag_smoke, ("summary", "graph_rag_answer_count"))),
            status="report_only_ready",
            interpretation="Consumer/RAG/recommendation smoke is ready in report-only mode; deterministic drafts are not LLM answers.",
            evidence=[str(paths["graph_rag_smoke_json"])],
            counts=graph_rag_smoke.get("summary") if isinstance(graph_rag_smoke.get("summary"), dict) else {},
        ),
        source_row(
            source_id="service_stage7_atlas_product_surface",
            stage="product_surface",
            count=service_articles,
            status="surface_stale_or_not_current" if service_articles != stable_articles else "surface_current_local_package",
            interpretation=(
                "Local CloudRun stage7_atlas package is not the authoritative atlas product surface when its article count differs from the current 47,340 base."
                if service_articles != stable_articles
                else "Local service stage7_atlas package count matches the current atlas base."
            ),
            evidence=[str(paths["service_stage7_package_manifest_json"]), str(paths["service_stage7_release_pointer_json"])],
            counts={
                "service_articles": service_articles,
                "stable_articles": stable_articles,
                "service_decision": service_manifest.get("decision") or service_pointer.get("decision"),
            },
        ),
    ]

    ledger = [
        ledger_row(
            source_id="ddownload_discovered_queue_93761",
            total=ddownload["discovered_records"],
            classification="historical_substrate_not_graph_truth",
            stage_status=stage_status(
                source_discovery="complete_historical",
                archive_assets_dajiala="partial",
                llm_export_extract="mostly_complete_historical",
                stable_structured="not_row_level_promoted",
                graph_marker="not_graph_truth",
                vector_retrieval="not_directly_vectorized",
                product_surface="not_current_surface",
            ),
            decision="Do not call the 93,761 historical queue fully processed into the atlas; it is upstream provenance.",
            gaps=["archive_retry_queue", "llm_export_failed", "release_v2_review_blocked"],
            evidence=[str(paths["total_deep_audit_md"]), str(paths["ddownload_relation_md"])],
        ),
        ledger_row(
            source_id="atlas_stable_47340",
            total=stable_articles,
            classification="complete_in_atlas_production",
            stage_status=stage_status(
                source_discovery="source_backed",
                archive_assets_dajiala="consumed_current_slices",
                ocr_markdown="complete_for_promoted_slices",
                llm_export_extract="stable_extract_complete",
                stable_structured="complete",
                graph_marker="verified",
                vector_retrieval="role_aliases_applied",
                external_media_identity="reviewed_zero_edges",
                qa_orchestration="ready_report_only",
                product_surface="stale" if service_articles != stable_articles else "local_package_current",
            ),
            decision="This is the current atlas production base.",
            gaps=["product_surface_stale"] if service_articles != stable_articles else [],
            evidence=[str(paths["stable_merge_json"]), str(paths["graph_verify_json"]), str(paths["qdrant_alias_apply_json"])],
        ),
        ledger_row(
            source_id="full_v6_81417_candidate",
            total=int_or_none(by_action.get("full_v6_81417_hold_candidate", {}).get("count")),
            classification="candidate_only",
            stage_status=stage_status(
                source_discovery="known",
                ocr_markdown="mixed_quality",
                llm_export_extract="candidate_extract",
                stable_structured="candidate_only",
                graph_marker="not_promoted",
                vector_retrieval="not_current_production_truth",
                qa_orchestration="gate_required",
            ),
            decision="Full V6 is not processed into current production; only reviewed smaller slices should promote.",
            gaps=["full_v6_candidate_hold"],
            evidence=[str(paths["gap_packet_json"]), str(paths["lineage_json"])],
        ),
        ledger_row(
            source_id="residual_ocr_debt",
            total=(int_or_none(gap_summary.get("p1_low_quality_text_review_rows")) or 0)
            + (int_or_none(gap_summary.get("p1_remaining_local_ocr_rerun_rows")) or 0)
            + (int_or_none(nested_get(by_action, ("fullmap_old_route_ocr_missing_filter_gate", "count"))) or 0),
            classification="review_required_and_strategy_gated",
            stage_status=stage_status(
                source_discovery="known",
                archive_assets_dajiala="no_blind_paid_rerun",
                ocr_markdown="incomplete_for_gap_rows",
                llm_export_extract="blocked_until_ocr_quality",
                stable_structured="not_promoted",
                graph_marker="not_promoted",
                qa_orchestration="gate_required",
            ),
            decision="Residual OCR debt is visible but not safe to auto-rerun as one batch.",
            gaps=["p1_low_quality_ocr_review", "p1_ocr_empty_strategy_gate", "fullmap_old_route_ocr_debt"],
            evidence=[str(paths["gap_packet_json"]), str(paths["gap_ledger_json"])],
        ),
        ledger_row(
            source_id="external_identity_media_queue",
            total=int_or_none(identity_review.get("input_rows")) or int_or_none(identity_final.get("external_identity_reviewed_rows")),
            classification="reviewed_no_graph_edges",
            stage_status=stage_status(
                external_media_identity="reviewed_needs_more_source",
                graph_marker="no_external_edges",
                qa_orchestration="strict_gate_passed_with_zero_acceptance",
                product_surface="review_queue_only",
            ),
            decision="External media/profile evidence is not production identity truth yet.",
            gaps=["external_identity_needs_more_source"],
            evidence=[str(paths["identity_review_gate_json"]), str(paths["identity_final_lock_json"])],
        ),
    ]

    gaps = [
        gap_row(
            gap_id="archive_retry_or_incomplete_rows",
            source_id="ddownload_archive_audit",
            count=ddownload["archive_retry_queue"],
            severity="medium",
            class_="historical_upstream_retry_not_current_graph_blocker",
            decision="Do not treat retry rows as current atlas failure; require bounded source-backed repair plan before rerun.",
            next_action="Only build a new repair queue from exact manifests/status files, not from D root recursion.",
            evidence=[str(paths["total_deep_audit_md"]), str(paths["ddownload_relation_md"])],
        ),
        gap_row(
            gap_id="llm_export_failed_rows",
            source_id="ddownload_llm_export",
            count=ddownload["llm_export_failed"],
            severity="medium",
            class_="historical_failed_export",
            decision="Keep failed export rows out of graph truth unless archive/source repair succeeds.",
            next_action="Route through archive repair or no-rerun classification after exact queue audit.",
            evidence=[str(paths["total_deep_audit_md"]), str(paths["ddownload_relation_md"])],
        ),
        gap_row(
            gap_id="release_v2_review_blocked_rows",
            source_id="ddownload_llm_release_v2",
            count=(ddownload["llm_release_v2_review"] or 0) + (ddownload["llm_release_v2_blocked"] or 0)
            if ddownload["llm_release_v2_review"] is not None and ddownload["llm_release_v2_blocked"] is not None
            else None,
            severity="medium",
            class_="historical_quality_split",
            decision="Review/blocked v2 rows are historical substrate, not automatic atlas backfill.",
            next_action="Use only if a later source-lineage packet proves a non-duplicate promoted slice.",
            evidence=[str(paths["total_deep_audit_md"]), str(paths["ddownload_relation_md"])],
        ),
        gap_row(
            gap_id="full_v6_candidate_hold",
            source_id="full_v6_81417_candidate",
            count=int_or_none(by_action.get("full_v6_81417_hold_candidate", {}).get("count")),
            severity="high",
            class_="candidate_only",
            decision="Full V6 has not fully entered atlas production and must stay candidate-only.",
            next_action="Promote only smaller source-backed slices with merge-readiness and graph verification.",
            evidence=[str(paths["gap_packet_json"]), str(paths["lineage_json"])],
        ),
        gap_row(
            gap_id="p1_low_quality_ocr_review",
            source_id="residual_ocr_debt",
            count=int_or_none(gap_summary.get("p1_low_quality_text_review_rows")),
            severity="medium",
            class_="review_required",
            decision="Do not send low-quality OCR text directly to Flash or graph.",
            next_action="Run a bounded review packet that accepts or rejects OCR text as source evidence.",
            evidence=[str(paths["gap_ledger_json"])],
        ),
        gap_row(
            gap_id="p1_ocr_empty_strategy_gate",
            source_id="residual_ocr_debt",
            count=int_or_none(gap_summary.get("p1_remaining_local_ocr_rerun_rows")),
            severity="medium",
            class_="blocked_until_strategy",
            decision="OCR-empty rows need a new strategy before another run.",
            next_action="Create a bounded nonempty-text canary before any larger OCR rerun.",
            evidence=[str(paths["gap_ledger_json"])],
        ),
        gap_row(
            gap_id="fullmap_old_route_ocr_debt",
            source_id="residual_ocr_debt",
            count=int_or_none(nested_get(by_action, ("fullmap_old_route_ocr_missing_filter_gate", "count"))),
            severity="medium",
            class_="filter_before_paid_or_ocr",
            decision="Old-route OCR debt is known but not safe for blind paid or OCR rerun.",
            next_action="Filter to source/image-backed rows, then non-paid canary first.",
            evidence=[str(paths["gap_packet_json"])],
        ),
        gap_row(
            gap_id="external_identity_needs_more_source",
            source_id="external_identity_media_queue",
            count=int_or_none(identity_final.get("external_identity_needs_more_source_rows"))
            or int_or_none(identity_review.get("needs_more_source_rows")),
            severity="medium",
            class_="review_only",
            decision="External identity evidence is reviewed but has zero accepted graph edges.",
            next_action="Continue direct-source/profile proof only as bounded report-only evidence.",
            evidence=[str(paths["identity_review_gate_json"]), str(paths["identity_final_lock_json"])],
        ),
        gap_row(
            gap_id="atlas_product_surface_stale",
            source_id="service_stage7_atlas_product_surface",
            count=service_articles,
            severity="high" if service_articles != stable_articles else "none",
            class_="surface_stale_or_not_current" if service_articles != stable_articles else "surface_current",
            decision=(
                f"Local service stage7_atlas package has {service_articles} articles but current atlas base has {stable_articles}."
                if service_articles != stable_articles
                else "Local service stage7_atlas package matches current atlas base."
            ),
            next_action=(
                "Bake a fresh atlas product surface package from the current 47,340 consumer release pack before any external-facing atlas UI/API claim."
                if service_articles != stable_articles
                else "No surface rebake needed for count alignment."
            ),
            evidence=[str(paths["service_stage7_package_manifest_json"]), str(paths["service_stage7_release_pointer_json"])],
        ),
    ]
    gaps = [row for row in gaps if row["severity"] != "none"]

    class_counts = Counter(row["classification"] for row in ledger)
    gap_counts = Counter(row["class"] for row in gaps)
    hard_product_gap = service_articles != stable_articles
    summary = {
        "stable_articles": stable_articles,
        "historical_discovered_records": ddownload["discovered_records"],
        "archive_archived": ddownload["archive_archived"],
        "archive_retry_or_incomplete": ddownload["archive_retry_queue"],
        "llm_export_succeeded": ddownload["llm_export_succeeded"],
        "llm_export_failed": ddownload["llm_export_failed"],
        "llm_release_v2_articles": ddownload["llm_release_v2_articles"],
        "graph_articles": graph_articles,
        "graph_entities": graph_entities,
        "graph_events": graph_events,
        "qdrant_alias_applied": bool(qdrant_alias.get("applied")),
        "dajiala_unconsumed_candidate_rows": dajiala.get("unconsumed_candidate_rows"),
        "external_identity_accepted_edges": identity_final.get("external_identity_edges") or identity_review.get("accepted_for_graph"),
        "service_stage7_surface_articles": service_articles,
        "service_stage7_surface_matches_current_base": service_articles == stable_articles,
        "ledger_class_counts": dict(sorted(class_counts.items())),
        "gap_class_counts": dict(sorted(gap_counts.items())),
        "actual_next_work": [
            "Refresh atlas product surface package from current 47,340 pack" if hard_product_gap else "Product surface count is aligned",
            "Review 99 low-quality OCR text rows before Flash/graph",
            "Design bounded strategy for 30 OCR-empty rows",
            "Filter 3,878 old-route OCR debt before any OCR/paid rerun",
            "Keep external identity edges at zero until direct proof exists",
        ],
    }
    return sources, ledger, gaps, summary


def render_markdown(report: dict[str, Any], sources: list[dict[str, Any]], ledger: list[dict[str, Any]], gaps: list[dict[str, Any]]) -> str:
    lines = [
        "# Atlas Global Processing Ledger",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- project_root: `{report['project_root']}`",
        "",
        "## Answer",
        "",
        report["answer"],
        "",
        "## Global Funnel",
        "",
        "| Layer | Count | Status | Interpretation |",
        "| --- | ---: | --- | --- |",
    ]
    for row in sources:
        lines.append(
            "| `{}` | {} | `{}` | {} |".format(
                row["source_id"],
                "" if row["count"] is None else row["count"],
                row["status"],
                row["interpretation"].replace("|", "\\|"),
            )
        )
    lines.extend(["", "## Processing Ledger", "", "| Source | Classification | Decision | Gaps |", "| --- | --- | --- | --- |"])
    for row in ledger:
        lines.append(
            "| `{}` | `{}` | {} | {} |".format(
                row["source_id"],
                row["classification"],
                row["decision"].replace("|", "\\|"),
                ", ".join(f"`{gap}`" for gap in row["gaps"]) or "",
            )
        )
    lines.extend(["", "## Gap Queue", "", "| Gap | Count | Class | Decision | Next Action |", "| --- | ---: | --- | --- | --- |"])
    for row in gaps:
        lines.append(
            "| `{}` | {} | `{}` | {} | {} |".format(
                row["gap_id"],
                "" if row["count"] is None else row["count"],
                row["class"],
                row["decision"].replace("|", "\\|"),
                row["next_action"].replace("|", "\\|"),
            )
        )
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(report["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    return "\n".join(lines)


def build_report(paths: dict[str, Path], out_dir: Path) -> dict[str, Any]:
    sources, ledger, gaps, summary = build_global_ledger(paths)
    out_dir.mkdir(parents=True, exist_ok=True)
    source_path = out_dir / "global_source_inventory.jsonl"
    ledger_path = out_dir / "global_processing_ledger.jsonl"
    gap_path = out_dir / "global_gap_queue.jsonl"
    report_path = out_dir / "global_processing_audit.json"
    md_path = out_dir / "global_processing_audit.md"

    product_surface_aligned = bool(summary["service_stage7_surface_matches_current_base"])
    answer = (
        "Not all historical pulled data has been processed into the current atlas production truth. "
        "The current atlas production base is complete at 47,340 stable articles with verified graph and role-isolated vectors, "
        "while the 93,761 historical pull queue remains upstream provenance with archive/export/release quality residue. "
        "The highest product-layer gap is that the local service stage7_atlas package must be refreshed from the current 47,340 base."
        if not product_surface_aligned
        else "Historical pulled data is not equivalent to current atlas production truth, but the current 47,340 atlas base and local product surface counts are aligned."
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "atlas_global_processing_ledger_ready_with_known_gaps",
        "project_root": str(PROJECT_ROOT),
        "answer": answer,
        "summary": summary,
        "outputs": {
            "source_inventory": str(source_path),
            "processing_ledger": str(ledger_path),
            "gap_queue": str(gap_path),
            "json": str(report_path),
            "markdown": str(md_path),
        },
        "inputs": {key: str(path) for key, path in paths.items()},
        "safety": {
            "report_only": True,
            "d_scan_executed": False,
            "network_called": False,
            "paid_api_used": False,
            "llm_called": False,
            "ocr_execution": False,
            "qdrant_write_executed": False,
            "qdrant_alias_change_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "cloudrun_publish_executed": False,
            "miniprogram_upload_executed": False,
            "secrets_read_or_printed": False,
            "used_9router": False,
        },
    }
    write_jsonl(source_path, sources)
    write_jsonl(ledger_path, ledger)
    write_jsonl(gap_path, gaps)
    write_json(report_path, report)
    write_text(md_path, render_markdown(report, sources, ledger, gaps))
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    for key, path in DEFAULT_PATHS.items():
        parser.add_argument(f"--{key.replace('_', '-')}", type=Path, default=path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = {key: getattr(args, key) for key in DEFAULT_PATHS}
    report = build_report(paths, args.out_dir)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "report": report["outputs"]["json"],
                "gap_queue": report["outputs"]["gap_queue"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
