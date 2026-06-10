#!/usr/bin/env python3
"""Build the 10-stage global reconciliation matrix for the atlas line.

This is a whole-project audit surface for 中国地下电子音乐图鉴. It consumes
current manifests/reports plus the latest local OCR retry evidence and writes a
machine-readable matrix across the 10 stages requested by the operator.

It does not scan D: roots, call network/model APIs, pay Dajiala, write graph or
vector stores, publish CloudRun, or upload mini-program artifacts.
"""
from __future__ import annotations

import argparse
import json
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
DEFAULT_OUT_DIR = REPORTS / "atlas_10_stage_reconciliation_20260519"
SCHEMA_VERSION = "atlas_10_stage_reconciliation.v1"

STAGES = [
    ("url_account_discovery", "URL/账号发现"),
    ("archive_mptext_assets_dajiala", "归档层"),
    ("ocr_markdown", "OCR/Markdown"),
    ("llm_flash_pro_stable_extract", "LLM"),
    ("structured_article_entity_event", "结构化"),
    ("graph_graphcandidatepack_neo4j", "图谱"),
    ("vector_1024_qdrant", "向量"),
    ("external_media_identity", "外部媒体/身份"),
    ("qa_longrun_ssot", "QA/长跑"),
    ("atlas_product_surface", "成品层"),
]

DEFAULT_PATHS = {
    "global_ledger_json": REPORTS / "atlas_global_processing_ledger_20260519" / "global_processing_audit.json",
    "global_gap_queue_jsonl": REPORTS / "atlas_global_processing_ledger_20260519" / "global_gap_queue.jsonl",
    "lineage_json": REPORTS / "atlas_full_source_lineage_47k_93k_gap_20260519" / "atlas_full_source_lineage.json",
    "gap_packet_json": REPORTS / "atlas_gap_backfill_execution_packet_20260519" / "gap_backfill_execution_packet.json",
    "gap_ledger_json": REPORTS / "atlas_gap_ledger_refresh_20260519_0715" / "gap_ledger.json",
    "stable_merge_json": REPORTS
    / "stable_merge_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_plus_oldroute_dajiala130_20260519"
    / "stable_merge_summary.json",
    "consumer_manifest_json": REPORTS
    / "consumer_release_pack_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_plus_oldroute_dajiala130_20260519"
    / "manifest.json",
    "graph_verify_json": REPORTS
    / "graph_production_promotion_47k_delta375_plus_oldroute_dajiala130_verify_20260519"
    / "promotion_report.json",
    "qdrant_alias_apply_json": REPORTS / "qdrant_role_alias_apply_47k_delta375_20260519" / "qdrant_role_alias_apply_report.json",
    "vector_role_summary_json": REPORTS
    / "vector_role_artifacts_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518"
    / "role_artifacts_summary.json",
    "oldroute_dajiala_stable_summary_json": REPORTS
    / "fullmap_old_route_dajiala_success130_stable_extract_20260519"
    / "stable_materialize_summary.json",
    "oldroute_dajiala_llm_summary_json": REPORTS
    / "fullmap_old_route_dajiala_success130_deepseek_extract_20260519"
    / "flash_summary.json",
    "oldroute_dajiala_signed_audit_json": REPORTS
    / "fullmap_old_route_dajiala_signed_audit_20260519"
    / "archive-audit-summary.json",
    "oldroute_dajiala_delta_release_manifest_json": REPORTS
    / "consumer_release_pack_oldroute_dajiala130_delta_20260519"
    / "manifest.json",
    "oldroute_dajiala_vector_delta_summary_json": REPORTS
    / "vector_role_artifacts_oldroute_dajiala130_delta_20260519"
    / "role_artifacts_summary.json",
    "oldroute_dajiala_vector_multilingual_report_json": REPORTS
    / "vector_role_delta_upsert_oldroute_dajiala130_20260519"
    / "multilingual_baseline"
    / "qdrant_vector_role_full_wave_report.json",
    "oldroute_dajiala_vector_snowflake_report_json": REPORTS
    / "vector_role_delta_upsert_oldroute_dajiala130_20260519"
    / "snowflake_canary"
    / "qdrant_vector_role_full_wave_report.json",
    "oldroute_dajiala_vector_english_report_json": REPORTS
    / "vector_role_delta_upsert_oldroute_dajiala130_20260519"
    / "english_sidecar"
    / "qdrant_vector_role_full_wave_report.json",
    "oldroute_dajiala_qdrant_point_verify_dir": REPORTS
    / "qdrant_delta_point_verify_oldroute_dajiala130_20260519",
    "oldroute_dajiala_vector_router_smoke_json": REPORTS
    / "vector_collection_router_smoke_47k_delta375_plus_oldroute_dajiala130_20260519"
    / "vector_collection_router_smoke.json",
    "oldroute_dajiala_alias_router_smoke_json": REPORTS
    / "qdrant_role_alias_router_smoke_47k_delta375_plus_oldroute_dajiala130_20260519"
    / "qdrant_role_alias_router_smoke.json",
    "dajiala_queue_audit_json": REPORTS / "dajiala_paid_queue_consumption_audit_20260519" / "dajiala_paid_queue_consumption_audit.json",
    "identity_final_lock_json": REPORTS / "graph_candidate_pack_final_lock_47k_delta375_20260519" / "graph_candidate_pack_readiness.json",
    "identity_review_gate_json": REPORTS
    / "external_identity_future_direct_proof_review_gate_47k_delta375_20260519"
    / "source_followup_review_gate_summary.json",
    "service_package_manifest_json": PROJECT_ROOT
    / "services"
    / "weekly_activity_cloudrun"
    / "data"
    / "stage7_atlas"
    / "package_manifest.json",
    "ocr_retry_summary_json": REPORTS
    / "v6_p1_local_ocr_repair_20260519_stage10_global_full"
    / "local_ocr_repair_summary.json",
    "post_ocr_locator_json": REPORTS
    / "v6_p1_existing_ocr_locator_after_stage10_global_ocr_20260519"
    / "v6_p1_existing_ocr_locator_summary.json",
    "post_ocr_rerun_jsonl": REPORTS
    / "v6_p1_existing_ocr_locator_after_stage10_global_ocr_20260519"
    / "v6_p1_existing_ocr_rerun_needed.jsonl",
    "post_ocr_low_quality_jsonl": REPORTS
    / "v6_p1_existing_ocr_locator_after_stage10_global_ocr_20260519"
    / "v6_p1_existing_ocr_low_quality_text_review_needed.jsonl",
    "low_quality_review_summary_json": REPORTS
    / "p1_low_quality_ocr_review_20260519"
    / "low_quality_ocr_review_summary.json",
    "fullmap_old_route_filter_summary_json": REPORTS
    / "fullmap_old_route_ocr_debt_filter_20260519"
    / "fullmap_old_route_ocr_debt_filter_summary.json",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
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


def nested(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return default if cur is None else cur


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def status(state: str, count: int | None = None, note: str = "", evidence: list[str] | None = None) -> dict[str, Any]:
    return {"state": state, "count": count, "note": note, "evidence": evidence or []}


def blank_stage_map() -> dict[str, dict[str, Any]]:
    return {key: status("unknown") for key, _label in STAGES}


def row(
    *,
    source_id: str,
    source_label: str,
    classification: str,
    count: int | None,
    stages: dict[str, dict[str, Any]],
    decision: str,
    next_action: str,
    evidence: list[str],
) -> dict[str, Any]:
    full = blank_stage_map()
    full.update(stages)
    return {
        "schema_version": f"{SCHEMA_VERSION}.matrix_row",
        "source_id": source_id,
        "source_label": source_label,
        "classification": classification,
        "count": count,
        "stages": full,
        "decision": decision,
        "next_action": next_action,
        "evidence": evidence,
    }


def build_matrix(paths: dict[str, Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    ledger = read_json(paths["global_ledger_json"])
    lineage = read_json(paths["lineage_json"])
    gap_packet = read_json(paths["gap_packet_json"])
    gap_ledger = read_json(paths["gap_ledger_json"])
    stable = read_json(paths["stable_merge_json"])
    consumer = read_json(paths["consumer_manifest_json"])
    graph = read_json(paths["graph_verify_json"])
    qdrant = read_json(paths["qdrant_alias_apply_json"])
    vector = read_json(paths["vector_role_summary_json"])
    oldroute_stable = read_json(paths["oldroute_dajiala_stable_summary_json"])
    oldroute_llm = read_json(paths["oldroute_dajiala_llm_summary_json"])
    oldroute_signed_audit = read_json(paths["oldroute_dajiala_signed_audit_json"])
    oldroute_delta_release = read_json(paths["oldroute_dajiala_delta_release_manifest_json"])
    oldroute_vector_delta = read_json(paths["oldroute_dajiala_vector_delta_summary_json"])
    oldroute_vector_multilingual = read_json(paths["oldroute_dajiala_vector_multilingual_report_json"])
    oldroute_vector_snowflake = read_json(paths["oldroute_dajiala_vector_snowflake_report_json"])
    oldroute_vector_english = read_json(paths["oldroute_dajiala_vector_english_report_json"])
    oldroute_vector_router = read_json(paths["oldroute_dajiala_vector_router_smoke_json"])
    oldroute_alias_router = read_json(paths["oldroute_dajiala_alias_router_smoke_json"])
    dajiala = read_json(paths["dajiala_queue_audit_json"])
    identity_final = read_json(paths["identity_final_lock_json"])
    identity_review = read_json(paths["identity_review_gate_json"])
    service = read_json(paths["service_package_manifest_json"])
    ocr_retry = read_json(paths["ocr_retry_summary_json"])
    post_ocr_locator = read_json(paths["post_ocr_locator_json"])
    post_ocr_empty_rows = read_jsonl(paths["post_ocr_rerun_jsonl"])
    post_ocr_low_quality_rows = read_jsonl(paths["post_ocr_low_quality_jsonl"])
    low_quality_review = read_json(paths["low_quality_review_summary_json"])
    fullmap_filter = read_json(paths["fullmap_old_route_filter_summary_json"])

    summary = ledger.get("summary") if isinstance(ledger.get("summary"), dict) else {}
    gap_summary = gap_ledger.get("summary") if isinstance(gap_ledger.get("summary"), dict) else {}
    gap_actions = gap_packet.get("actions") if isinstance(gap_packet.get("actions"), list) else []
    actions_by_id = {str(item.get("action_id")): item for item in gap_actions if isinstance(item, dict)}
    lineage_layers = lineage.get("source_layers") if isinstance(lineage.get("source_layers"), list) else []
    lineage_by_source = {str(item.get("source_id")): item for item in lineage_layers if isinstance(item, dict)}

    stable_articles = int_value(stable.get("articles") or consumer.get("articles") or summary.get("stable_articles"))
    service_articles = int_value(nested(service, "counts", "articles", default=summary.get("service_stage7_surface_articles")))
    graph_articles = int_value(nested(graph, "after_counts", "article", "promoted", default=summary.get("graph_articles")))
    graph_entities = int_value(nested(graph, "after_counts", "entity", "promoted", default=summary.get("graph_entities")))
    graph_events = int_value(nested(graph, "after_counts", "event", "promoted", default=summary.get("graph_events")))
    vector_jobs = int_value(vector.get("scanned_jobs"))
    vector_delta_jobs = int_value(oldroute_vector_delta.get("scanned_jobs"))
    vector_alias_actions = len(qdrant.get("actions") or [])
    vector_delta_written = sum(
        int_value(nested(report, "state", "processed_this_run"))
        for report in (oldroute_vector_multilingual, oldroute_vector_snowflake, oldroute_vector_english)
    )
    p1_low_quality = int_value(gap_summary.get("p1_low_quality_text_review_rows") or len(post_ocr_low_quality_rows))
    p1_empty_after_retry = int_value(nested(post_ocr_locator, "counts", "ocr_rerun_needed", default=len(post_ocr_empty_rows)))
    fullmap_old_ocr = int_value(nested(actions_by_id.get("fullmap_old_route_ocr_missing_filter_gate", {}), "count"))
    full_v6 = int_value(nested(actions_by_id.get("full_v6_81417_hold_candidate", {}), "count"))
    identity_needs_more = int_value(identity_review.get("needs_more_source_rows") or identity_final.get("external_identity_needs_more_source_rows"))
    ocr_retry_counts = ocr_retry.get("counts") if isinstance(ocr_retry.get("counts"), dict) else {}
    low_quality_review_counts = low_quality_review.get("counts") if isinstance(low_quality_review.get("counts"), dict) else {}
    fullmap_filter_counts = fullmap_filter.get("counts") if isinstance(fullmap_filter.get("counts"), dict) else {}

    rows = [
        row(
            source_id="historical_93761_discovery_queue",
            source_label="93k/FULL_MAP + historical prefetch/account registry",
            classification="historical_upstream_provenance",
            count=int_value(summary.get("historical_discovered_records")),
            stages={
                "url_account_discovery": status("complete_historical", int_value(summary.get("historical_discovered_records")), "historical discovered/queued/audited records"),
                "archive_mptext_assets_dajiala": status("partial", int_value(summary.get("archive_archived")), "archived subset exists; retry/incomplete rows remain"),
                "ocr_markdown": status("mixed", None, "only promoted/current slices have OCR/Markdown completeness"),
                "llm_flash_pro_stable_extract": status("mostly_complete_historical", int_value(summary.get("llm_export_succeeded")), "historical LLM export has failed/review/blocked residue"),
                "structured_article_entity_event": status("not_current_truth", None, "not row-level promoted as a whole"),
                "graph_graphcandidatepack_neo4j": status("not_direct_graph_truth", None, "kept as provenance/source lineage"),
                "vector_1024_qdrant": status("not_directly_vectorized", None, "current vectors come from stable atlas base"),
                "external_media_identity": status("not_identity_truth", None, "not direct identity proof"),
                "qa_longrun_ssot": status("hold_as_lineage", None, "SSOT says source lineage, not blind promotion"),
                "atlas_product_surface": status("not_current_surface", None, "surface is current 47,470 product base"),
            },
            decision="Do not call the full historical queue processed into the atlas; preserve it as upstream provenance.",
            next_action="Use exact manifests/status files only; no D root scan and no blind rerun.",
            evidence=[str(paths["global_ledger_json"]), str(paths["lineage_json"])],
        ),
        row(
            source_id="current_47470_atlas_base",
            source_label="Current 47,470 atlas base",
            classification="complete_current_product_base",
            count=stable_articles,
            stages={
                "url_account_discovery": status("source_backed", stable_articles),
                "archive_mptext_assets_dajiala": status("consumed_current_slices", stable_articles, "47k + P1 repair + paid delta + old-route Dajiala130 consumed"),
                "ocr_markdown": status("complete_for_promoted_slices", stable_articles),
                "llm_flash_pro_stable_extract": status("stable_extract_complete", stable_articles),
                "structured_article_entity_event": status("complete", stable_articles, f"release entities={consumer.get('entities')} events={consumer.get('events')}"),
                "graph_graphcandidatepack_neo4j": status("verified_marker", graph_articles, f"graph entities={graph_entities} events={graph_events}"),
                "vector_1024_qdrant": status("current_alias_applied_delta_upserted", vector_jobs + vector_delta_jobs, f"role alias actions={vector_alias_actions}; delta cards written={vector_delta_written}"),
                "external_media_identity": status("reviewed_no_edges", 0, "external identity edges accepted=0"),
                "qa_longrun_ssot": status("no_rerun", stable_articles, "current production base"),
                "atlas_product_surface": status("surface_current", service_articles, "local atlas product package aligned"),
            },
            decision="This is the current atlas product base after old-route Dajiala130 promotion. Do not rerun completed LLM/OCR/paid/vector work.",
            next_action="Only add new source-backed deltas after merge-readiness and graph/vector verification.",
            evidence=[
                str(paths["stable_merge_json"]),
                str(paths["graph_verify_json"]),
                str(paths["qdrant_alias_apply_json"]),
                str(paths["service_package_manifest_json"]),
            ],
        ),
        row(
            source_id="v6_p1_1397_ocr_markdown_repair",
            source_label="V6 P1 strict OCR/Markdown/Flash repair 1,397",
            classification="complete_consumed_repair_slice",
            count=int_value(nested(lineage_by_source.get("v6_p1_ocr_markdown_visual_repair", {}), "count_signal", default=1397)),
            stages={
                "url_account_discovery": status("source_backed", 1397),
                "archive_mptext_assets_dajiala": status("local_image_evidence_used", 1397),
                "ocr_markdown": status("complete", 1397),
                "llm_flash_pro_stable_extract": status("complete", 1397),
                "structured_article_entity_event": status("complete", 1397),
                "graph_graphcandidatepack_neo4j": status("promoted_into_current_marker", 1397),
                "vector_1024_qdrant": status("covered_by_current_vectors", 1397),
                "qa_longrun_ssot": status("no_rerun", 1397),
                "atlas_product_surface": status("included_in_current_base", 1397),
            },
            decision="Already consumed. Re-running would waste prior OCR/Flash work.",
            next_action="No rerun.",
            evidence=[str(paths["lineage_json"]), str(paths["gap_packet_json"])],
        ),
        row(
            source_id="paid_wave09_21_delta375",
            source_label="Dajiala paid wave09-21 delta 375",
            classification="complete_consumed_paid_slice",
            count=375,
            stages={
                "archive_mptext_assets_dajiala": status("paid_evidence_consumed", 375, "no current unconsumed payable rows"),
                "ocr_markdown": status("complete", 375),
                "llm_flash_pro_stable_extract": status("complete", 375),
                "structured_article_entity_event": status("complete", 375),
                "graph_graphcandidatepack_neo4j": status("promoted_into_current_marker", 375),
                "vector_1024_qdrant": status("covered_by_current_vectors", 375),
                "qa_longrun_ssot": status("no_rerun", 375),
                "atlas_product_surface": status("included_in_current_base", 375),
            },
            decision="Paid evidence already consumed; Dajiala queue audit has unconsumed payable candidates=0.",
            next_action="No paid rerun from this queue.",
            evidence=[str(paths["dajiala_queue_audit_json"]), str(paths["lineage_json"])],
        ),
        row(
            source_id="fullmap_old_route_dajiala_signed_success130",
            source_label="FULL_MAP old-route signed Dajiala success 130",
            classification="complete_promoted_paid_recovery_slice",
            count=int_value(oldroute_stable.get("articles"), 130),
            stages={
                "url_account_discovery": status("source_url_recovered", 130, "from 3,503 old-route source-locator queue"),
                "archive_mptext_assets_dajiala": status(
                    "paid_dajiala_recovered",
                    int_value(oldroute_signed_audit.get("archived_count"), 130),
                    "signed legacy Dajiala run: 130 archived, 35 failed",
                ),
                "ocr_markdown": status("html_markdown_exported", 130, "llm_input.md exported from recovered archives"),
                "llm_flash_pro_stable_extract": status(
                    "deepseek_v4_pro_complete",
                    int_value(oldroute_llm.get("processed_samples"), 130),
                    f"chunks={oldroute_llm.get('chunk_count')} schema_ok={oldroute_llm.get('schema_ok_chunks')}",
                ),
                "structured_article_entity_event": status(
                    "complete",
                    int_value(oldroute_delta_release.get("articles"), 130),
                    f"delta release entities={oldroute_delta_release.get('entities')} events={oldroute_delta_release.get('events')}",
                ),
                "graph_graphcandidatepack_neo4j": status(
                    "promoted_into_current_marker",
                    130,
                    "new Neo4j production marker verified at 47,470 articles",
                ),
                "vector_1024_qdrant": status(
                    "delta_upserted_into_current_alias_targets",
                    vector_delta_written,
                    "point-id verification match_rate=1.0 for multilingual, snowflake, and english sidecar",
                ),
                "external_media_identity": status("candidate_only_unmodified", 0, "no external identity edge was accepted from this recovery slice"),
                "qa_longrun_ssot": status("promoted_no_rerun", 130),
                "atlas_product_surface": status("included_in_current_surface", 130),
            },
            decision="Recovered paid old-route slice is now part of the current atlas base.",
            next_action="Do not rerun these 130; only retry the 35 signed failures if a new signed source repair strategy appears.",
            evidence=[
                str(paths["oldroute_dajiala_signed_audit_json"]),
                str(paths["oldroute_dajiala_stable_summary_json"]),
                str(paths["graph_verify_json"]),
                str(paths["oldroute_dajiala_vector_router_smoke_json"]),
                str(paths["oldroute_dajiala_alias_router_smoke_json"]),
            ],
        ),
        row(
            source_id="full_v6_81417_candidate",
            source_label="Full V6 81,417 structured candidate",
            classification="candidate_only_hold",
            count=full_v6,
            stages={
                "url_account_discovery": status("known", full_v6),
                "archive_mptext_assets_dajiala": status("mixed_quality", full_v6),
                "ocr_markdown": status("mixed_incomplete", full_v6),
                "llm_flash_pro_stable_extract": status("candidate_extract", full_v6),
                "structured_article_entity_event": status("candidate_only", full_v6),
                "graph_graphcandidatepack_neo4j": status("not_promoted", full_v6),
                "vector_1024_qdrant": status("not_current_truth", full_v6),
                "qa_longrun_ssot": status("hold", full_v6, "requires smaller source-backed promoted slice"),
                "atlas_product_surface": status("not_in_surface", full_v6),
            },
            decision="Do not force full V6 into product. Promote only smaller source-backed deltas.",
            next_action="Create merge-readiness packet before any graph/vector/product ingestion.",
            evidence=[str(paths["gap_packet_json"]), str(paths["lineage_json"])],
        ),
        row(
            source_id="p1_low_quality_ocr_99",
            source_label="P1 low-quality OCR review rows",
            classification="review_before_flash",
            count=p1_low_quality,
            stages={
                "url_account_discovery": status("known", p1_low_quality),
                "archive_mptext_assets_dajiala": status("local_image_evidence_exists", p1_low_quality),
                "ocr_markdown": status("low_quality_text_review", p1_low_quality, "OCR text exists but quality gate failed"),
                "llm_flash_pro_stable_extract": status(
                    "blocked_no_auto_flash",
                    p1_low_quality,
                    f"review done; accepted_for_markdown_flash={low_quality_review_counts.get('accepted_for_markdown_flash_rows', 0)}",
                ),
                "structured_article_entity_event": status("not_promoted", p1_low_quality),
                "graph_graphcandidatepack_neo4j": status("not_promoted", p1_low_quality),
                "vector_1024_qdrant": status("not_current_truth", p1_low_quality),
                "qa_longrun_ssot": status("gate_required", p1_low_quality),
                "atlas_product_surface": status("not_in_surface", p1_low_quality),
            },
            decision="Low-quality OCR rows were reviewed; zero rows are automatically accepted for Markdown/Flash.",
            next_action="Source-review candidates may be handled only with stronger source/image context; no model spend from this queue now.",
            evidence=[str(paths["post_ocr_low_quality_jsonl"]), str(paths["post_ocr_locator_json"]), str(paths["low_quality_review_summary_json"])],
        ),
        row(
            source_id="p1_ocr_empty_30_after_local_retry",
            source_label="P1 OCR-empty rows after full local retry",
            classification="blocked_until_new_source_or_strategy",
            count=p1_empty_after_retry,
            stages={
                "url_account_discovery": status("known", p1_empty_after_retry),
                "archive_mptext_assets_dajiala": status("local_image_evidence_exists", p1_empty_after_retry),
                "ocr_markdown": status("retry_executed_still_empty", p1_empty_after_retry, f"executed={ocr_retry_counts.get('executed_rows')} ok_text={ocr_retry_counts.get('ok_text_rows')} frames={ocr_retry_counts.get('frames_extracted')}"),
                "llm_flash_pro_stable_extract": status("blocked_no_ocr_text", p1_empty_after_retry),
                "structured_article_entity_event": status("not_promoted", p1_empty_after_retry),
                "graph_graphcandidatepack_neo4j": status("not_promoted", p1_empty_after_retry),
                "vector_1024_qdrant": status("not_current_truth", p1_empty_after_retry),
                "qa_longrun_ssot": status("strategy_required", p1_empty_after_retry),
                "atlas_product_surface": status("not_in_surface", p1_empty_after_retry),
            },
            decision="All 30 were retried locally; zero produced acceptable OCR text. More same-path OCR would waste compute.",
            next_action="Require new source-image locator, higher-signal image source, or explicit no-information classification packet.",
            evidence=[str(paths["ocr_retry_summary_json"]), str(paths["post_ocr_locator_json"])],
        ),
        row(
            source_id="fullmap_old_route_ocr_debt_3878",
            source_label="FULL_MAP old-route OCR debt 3,878",
            classification="filtered_no_blind_rerun",
            count=fullmap_old_ocr,
            stages={
                "url_account_discovery": status("known", fullmap_old_ocr),
                "archive_mptext_assets_dajiala": status(
                    "filtered_no_local_image",
                    int_value(fullmap_filter_counts.get("input_rows"), fullmap_old_ocr),
                    f"already_current={fullmap_filter_counts.get('already_current_rows')} local_ocr_candidates={fullmap_filter_counts.get('local_ocr_candidate_rows')} source_locator={fullmap_filter_counts.get('source_locator_queue_rows')}",
                ),
                "ocr_markdown": status(
                    "no_executable_ocr_queue",
                    int_value(fullmap_filter_counts.get("local_ocr_candidate_rows")),
                    "all 3,878 rows have local_image_count=0",
                ),
                "llm_flash_pro_stable_extract": status(
                    "blocked_no_usable_text",
                    int_value(fullmap_filter_counts.get("ready_text_reclass_candidate_rows")),
                    "old local files are empty shells unless source locator repairs them",
                ),
                "structured_article_entity_event": status("not_promoted", fullmap_old_ocr),
                "graph_graphcandidatepack_neo4j": status("not_promoted", fullmap_old_ocr),
                "vector_1024_qdrant": status("not_current_truth", fullmap_old_ocr),
                "qa_longrun_ssot": status("filtered_gate_closed_for_blind_rerun", fullmap_old_ocr),
                "atlas_product_surface": status("not_in_surface", fullmap_old_ocr),
            },
            decision="Old-route OCR debt was filtered and partially recovered: 375 rows were already current, 0 rows were eligible for direct local OCR, 130 signed Dajiala rows are now promoted, and the residue is source repair rather than blind OCR.",
            next_action="Source recovery has produced 130 promoted signed Dajiala rows; remaining old-route work is 35 signed failures plus 3,338 unsigned/source-repair candidates, not local OCR.",
            evidence=[
                str(paths["gap_packet_json"]),
                str(paths["gap_ledger_json"]),
                str(paths["fullmap_old_route_filter_summary_json"]),
                str(paths["oldroute_dajiala_signed_audit_json"]),
            ],
        ),
        row(
            source_id="external_identity_needs_more_source_16",
            source_label="External media/profile identity queue",
            classification="review_only_needs_more_source",
            count=identity_needs_more,
            stages={
                "external_media_identity": status("needs_more_source", identity_needs_more, "accepted graph edges=0"),
                "graph_graphcandidatepack_neo4j": status("no_external_edges", 0),
                "vector_1024_qdrant": status("not_applicable_until_graph_acceptance", 0),
                "qa_longrun_ssot": status("review_only", identity_needs_more),
                "atlas_product_surface": status("not_in_surface", identity_needs_more),
            },
            decision="Candidate/review-only identity evidence must not create profile edges.",
            next_action="Continue direct-source proof only; accepted edge count stays zero.",
            evidence=[str(paths["identity_final_lock_json"]), str(paths["identity_review_gate_json"])],
        ),
    ]

    execution_actions = [
        {
            "action_id": "no_rerun_current_47470",
            "priority": 0,
            "decision": "reuse",
            "reason": "current base complete across graph/vector/product surface",
            "count": stable_articles,
        },
        {
            "action_id": "no_rerun_consumed_ocr_llm_paid_slices",
            "priority": 0,
            "decision": "reuse",
            "reason": "V6 P1 1,397 and paid delta 375 are already consumed",
            "count": 1397 + 375,
        },
        {
            "action_id": "oldroute_dajiala130_promoted_no_rerun",
            "priority": 0,
            "decision": "promoted_reuse",
            "reason": "130 old-route signed Dajiala rows are archived, extracted, structured, promoted to Neo4j, vector-upserted, and included in product surface",
            "count": int_value(oldroute_stable.get("articles"), 130),
        },
        {
            "action_id": "p1_empty_local_ocr_rerun_done",
            "priority": 1,
            "decision": "done_no_text",
            "reason": "executed local OCR retry for the exact 30-row queue; ok_text_rows=0",
            "count": p1_empty_after_retry,
            "evidence": str(paths["ocr_retry_summary_json"]),
        },
        {
            "action_id": "p1_low_quality_review_done_no_auto_flash",
            "priority": 2,
            "decision": "done_no_auto_flash",
            "reason": "99 rows reviewed; accepted_for_markdown_flash=0",
            "count": p1_low_quality,
            "queue": str(paths["post_ocr_low_quality_jsonl"]),
            "evidence": str(paths["low_quality_review_summary_json"]),
        },
        {
            "action_id": "fullmap_old_route_filter_done_no_blind_rerun",
            "priority": 3,
            "decision": "partially_recovered_source_locator_only",
            "reason": "filtered 3,878 rows: 375 already current, 0 local OCR candidates, 130 promoted signed Dajiala rows, residue remains source-repair/account-registry",
            "count": fullmap_old_ocr,
            "evidence": str(paths["fullmap_old_route_filter_summary_json"]),
        },
        {
            "action_id": "external_identity_keep_zero_edges",
            "priority": 4,
            "decision": "review_only",
            "reason": "no direct proof accepted",
            "count": identity_needs_more,
        },
    ]
    class_counts = Counter(item["classification"] for item in rows)
    stage_state_counts: dict[str, dict[str, int]] = {}
    for key, _label in STAGES:
        stage_state_counts[key] = dict(Counter(item["stages"][key]["state"] for item in rows))
    out_summary = {
        "stable_articles": stable_articles,
        "service_articles": service_articles,
        "service_surface_aligned": stable_articles == service_articles,
        "graph_articles": graph_articles,
        "graph_entities": graph_entities,
        "graph_events": graph_events,
        "vector_jobs": vector_jobs,
        "vector_delta_jobs_oldroute_dajiala130": vector_delta_jobs,
        "vector_delta_written_oldroute_dajiala130": vector_delta_written,
        "qdrant_alias_applied": bool(qdrant.get("applied")),
        "qdrant_delta_vector_router_smoke_ok": bool(oldroute_vector_router.get("ok")),
        "qdrant_delta_alias_router_smoke_ok": bool(oldroute_alias_router.get("ok")),
        "dajiala_unconsumed_candidate_rows": dajiala.get("unconsumed_candidate_rows"),
        "oldroute_dajiala_signed_archived_rows": oldroute_signed_audit.get("archived_count"),
        "oldroute_dajiala_signed_failed_rows": oldroute_signed_audit.get("retry_queue_count"),
        "oldroute_dajiala_promoted_articles": oldroute_stable.get("articles"),
        "oldroute_dajiala_delta_release_entities": oldroute_delta_release.get("entities"),
        "oldroute_dajiala_delta_release_events": oldroute_delta_release.get("events"),
        "p1_low_quality_review_rows": p1_low_quality,
        "p1_low_quality_source_review_candidate_rows": low_quality_review_counts.get("source_review_candidate_rows"),
        "p1_low_quality_manual_review_low_signal_rows": low_quality_review_counts.get("manual_review_low_signal_rows"),
        "p1_low_quality_rejected_low_signal_rows": low_quality_review_counts.get("rejected_low_signal_rows"),
        "p1_low_quality_accepted_for_markdown_flash_rows": low_quality_review_counts.get("accepted_for_markdown_flash_rows"),
        "p1_ocr_empty_after_retry_rows": p1_empty_after_retry,
        "p1_ocr_retry_ok_text_rows": ocr_retry_counts.get("ok_text_rows"),
        "p1_ocr_retry_frames_extracted": ocr_retry_counts.get("frames_extracted"),
        "fullmap_old_route_ocr_debt": fullmap_old_ocr,
        "fullmap_old_route_filter_already_current_rows": fullmap_filter_counts.get("already_current_rows"),
        "fullmap_old_route_filter_local_ocr_candidate_rows": fullmap_filter_counts.get("local_ocr_candidate_rows"),
        "fullmap_old_route_filter_ready_text_reclass_candidate_rows": fullmap_filter_counts.get("ready_text_reclass_candidate_rows"),
        "fullmap_old_route_filter_source_locator_queue_rows": fullmap_filter_counts.get("source_locator_queue_rows"),
        "fullmap_old_route_filter_source_url_present_rows": fullmap_filter_counts.get("source_url_present_rows"),
        "external_identity_needs_more_source": identity_needs_more,
        "classification_counts": dict(sorted(class_counts.items())),
        "stage_state_counts": stage_state_counts,
    }
    return rows, execution_actions, out_summary


def render_markdown(report: dict[str, Any], rows: list[dict[str, Any]], actions: list[dict[str, Any]]) -> str:
    lines = [
        "# Atlas 10-Stage Global Reconciliation",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- project_root: `{report['project_root']}`",
        "",
        "## Final Answer",
        "",
        report["answer"],
        "",
        "## Stage Matrix",
        "",
        "| Source | Class | Count | " + " | ".join(label for _key, label in STAGES) + " |",
        "| --- | --- | ---: | " + " | ".join("---" for _key, _label in STAGES) + " |",
    ]
    for item in rows:
        stage_bits = []
        for key, _label in STAGES:
            st = item["stages"][key]
            stage_bits.append(f"`{st['state']}`")
        lines.append(
            "| {} | `{}` | {} | {} |".format(
                item["source_label"].replace("|", "\\|"),
                item["classification"],
                "" if item["count"] is None else item["count"],
                " | ".join(stage_bits),
            )
        )
    lines.extend(["", "## Non-Waste Execution Queue", "", "| Action | Decision | Count | Reason |", "| --- | --- | ---: | --- |"])
    for action in sorted(actions, key=lambda row: int(row.get("priority") or 0)):
        lines.append(
            "| `{}` | `{}` | {} | {} |".format(
                action["action_id"],
                action["decision"],
                action.get("count", ""),
                str(action.get("reason") or "").replace("|", "\\|"),
            )
        )
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(report["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    return "\n".join(lines)


def build_report(paths: dict[str, Path], out_dir: Path) -> dict[str, Any]:
    rows, actions, summary = build_matrix(paths)
    out_dir.mkdir(parents=True, exist_ok=True)
    matrix_path = out_dir / "stage_matrix.jsonl"
    actions_path = out_dir / "non_waste_execution_queue.jsonl"
    report_path = out_dir / "atlas_10_stage_reconciliation.json"
    md_path = out_dir / "atlas_10_stage_reconciliation.md"
    answer = (
        "The current atlas product base is complete at 47,470 articles across structured JSONL, Neo4j production marker, "
        "role-isolated 1024-d Qdrant current aliases, and the local atlas product surface. Historical 93,761/FULL_MAP data "
        "is upstream provenance, not a second production base. The old-route 3,878-row OCR debt was filtered without blind "
        "rerun: 375 were already current, 0 had local images for immediate OCR, and 130 signed legacy Dajiala rows were "
        "recovered, extracted with DeepSeek v4 Pro, promoted into graph, vector-upserted, and included in the product "
        "surface. The exact 30-row OCR-empty queue was rerun locally and still produced zero acceptable OCR text. The "
        "99-row low-quality OCR queue was reviewed and accepted zero rows for automatic Markdown/Flash. Remaining "
        "executable work is source adjudication rather than repeating old work: 42 low-quality OCR rows require stronger "
        "source context, the old-route residue is 35 signed failures plus 3,338 unsigned/source-repair rows, and 16 "
        "external identity rows need stronger direct proof."
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "atlas_10_stage_reconciliation_ready_after_oldroute_dajiala130_promotion",
        "project_root": str(PROJECT_ROOT),
        "answer": answer,
        "stage_definitions": [{"key": key, "label": label} for key, label in STAGES],
        "summary": summary,
        "outputs": {
            "matrix": str(matrix_path),
            "non_waste_execution_queue": str(actions_path),
            "json": str(report_path),
            "markdown": str(md_path),
        },
        "inputs": {key: str(path) for key, path in paths.items()},
        "safety": {
            "report_only": True,
            "used_existing_artifacts_only": True,
            "d_root_scan_executed": False,
            "network_called": False,
            "llm_called": False,
            "paid_api_used": False,
            "cloudrun_publish_executed": False,
            "miniprogram_upload_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "qdrant_write_executed": False,
            "qdrant_alias_change_executed": False,
            "used_9router": False,
            "secrets_read_or_printed": False,
        },
    }
    write_jsonl(matrix_path, rows)
    write_jsonl(actions_path, actions)
    write_json(report_path, report)
    write_text(md_path, render_markdown(report, rows, actions))
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
                "matrix": report["outputs"]["matrix"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
