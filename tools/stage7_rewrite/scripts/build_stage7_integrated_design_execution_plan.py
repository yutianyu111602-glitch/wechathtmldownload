#!/usr/bin/env python3
"""Build the Stage7 integrated design, plan, code, and execution ledger.

This is a report-only controller artifact. It consolidates current authority
docs, plan docs, live runner code, and runner evidence into one machine-readable
plan before any next longrun slice is executed.

It does not call paid APIs, deploy, write SQLite, mutate Qdrant/Neo4j/mem0, read
secrets, or scan D:.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
DEFAULT_OUT_DIR = Path("reports/stage7_integrated_design_execution_plan_20260518")
SCHEMA_VERSION = "stage7_integrated_design_execution_plan.v1"

DOC_EXCLUDE_PARTS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "artifacts",
    "logs",
    "node_modules",
    "reports",
}

AUTHORITY_ORDER = [
    "LONGRUN_STATE.md",
    "MASTER_PLAN_20260513.md",
    "STAGE7_SSOT_20260514.md",
    "NEXT_STAGE_GATES_20260513.md",
    "prds/PRD_MASTER_INDEX_20260515.md",
    "STAGE7_CODEX_GOAL_LONGRUN_RUNBOOK_20260515.md",
    "STAGE7_BIGSTEP_LONGRUN_PLAN_20260516.md",
    "STAGE7_FULL_PIPELINE_INTEGRATION_PLAN_20260518.md",
    "NETWORK_ENTITY_SEARCH_METHOD_AUDIT_20260517.md",
]

CODE_ENTRYPOINTS = [
    {
        "lane": "text_extract",
        "path": "scripts/stage7_deepseek_flash_pilot.py",
        "role": "DeepSeek text extraction runner",
    },
    {
        "lane": "text_extract",
        "path": "scripts/deepseek_hybrid_scorer.py",
        "role": "post extraction scoring",
    },
    {
        "lane": "text_extract",
        "path": "scripts/materialize_flash_stable_extracts.py",
        "role": "stable article materialization",
    },
    {
        "lane": "ocr_image",
        "path": "scripts/audit_ocr_md_deepseek_contract.py",
        "role": "OCR before Markdown/DeepSeek contract guard",
    },
    {
        "lane": "ocr_image",
        "path": "scripts/build_recovered_artifact_manifest.py",
        "role": "recovered artifact and OCR text manifest",
    },
    {
        "lane": "ocr_image",
        "path": "../../src/poster/runPosterOcrFallback.ts",
        "role": "GIF/WebP static-frame poster OCR fallback",
    },
    {
        "lane": "vector",
        "path": "scripts/run_vector_role_full_wave.py",
        "role": "resumable text vector full-wave writer",
    },
    {
        "lane": "vector",
        "path": "scripts/run_vector_collection_router_smoke.py",
        "role": "Qdrant current/staging collection router smoke",
    },
    {
        "lane": "vector",
        "path": "scripts/qdrant_poster_staging_writer.py",
        "role": "poster OCR text vector staging writer",
    },
    {
        "lane": "vector",
        "path": "scripts/qdrant_alias_promote.py",
        "role": "Qdrant current alias promotion",
    },
    {
        "lane": "graph",
        "path": "scripts/neo4j_stage7_staging_writer.py",
        "role": "Stage7 Neo4j staging writer",
    },
    {
        "lane": "graph",
        "path": "scripts/promote_graph_to_production.py",
        "role": "Neo4j production label promotion/verification",
    },
    {
        "lane": "graph",
        "path": "scripts/merge_ocr_entities_to_neo4j.py",
        "role": "OCR entity/event Neo4j staging merge",
    },
    {
        "lane": "retrieval_rag",
        "path": "scripts/build_graph_rag_recommendation_current_smoke.py",
        "role": "current graph/RAG/recommendation evidence aggregator",
    },
    {
        "lane": "consumer",
        "path": "scripts/build_consumer_release_pack.py",
        "role": "consumer release pack builder",
    },
    {
        "lane": "consumer",
        "path": "scripts/write_consumer_release_pointer.py",
        "role": "consumer release pointer writer",
    },
    {
        "lane": "consumer",
        "path": "../../services/weekly_activity_cloudrun/src/server.mjs",
        "role": "CloudRun weekly and Stage7 API server",
    },
    {
        "lane": "consumer",
        "path": "../../services/weekly_activity_cloudrun/src/stage7AtlasStore.mjs",
        "role": "packaged Stage7 atlas reader",
    },
    {
        "lane": "consumer",
        "path": "../../services/weekly_activity_cloudrun/scripts/bake_and_deploy.py",
        "role": "weekly CloudRun bake/deploy runner",
    },
    {
        "lane": "consumer",
        "path": "../../services/weekly_activity_cloudrun/scripts/direct_cloudbase_deploy.py",
        "role": "direct CloudBase API deploy fallback",
    },
    {
        "lane": "consumer",
        "path": "scripts/build_miniprogram_review_submission_boundary.py",
        "role": "miniprogram review/public-release local-runner boundary packet",
    },
    {
        "lane": "consumer",
        "path": "scripts/build_production_sqlite_surface_decision.py",
        "role": "production SQLite current-release-path surface decision",
    },
    {
        "lane": "memory_monitor",
        "path": "scripts/mem0_local_write_read_canary.py",
        "role": "local mem0 write/read canary",
    },
    {
        "lane": "memory_monitor",
        "path": "scripts/hermes_metrics_collector.py",
        "role": "Hermes metrics collection",
    },
    {
        "lane": "safety",
        "path": "scripts/stage7_safe_handoff_verify.ps1",
        "role": "mandatory safe handoff verification",
    },
]

EVIDENCE_SPECS = [
    {
        "id": "prd_status",
        "path": "reports/prd_longrun_status_20260518/prd_longrun_status.json",
        "decision_path": ["release_decision"],
        "ok_path": ["ok"],
    },
    {
        "id": "final_readiness",
        "path": "reports/final_full_pipeline_readiness_20260518/final_full_pipeline_readiness.json",
        "decision_path": ["decision"],
        "ok_path": ["ok"],
    },
    {
        "id": "launch_packet",
        "path": "reports/full_pipeline_launch_packet_20260518/full_pipeline_launch_packet.json",
        "decision_path": ["decision"],
        "ok_path": ["ok"],
    },
    {
        "id": "operation_packet",
        "path": "reports/full_pipeline_production_operation_packet_20260518/full_pipeline_production_operation_packet.json",
        "decision_path": ["decision"],
        "ok_path": ["ok"],
    },
    {
        "id": "cloudrun_deploy",
        "path": "reports/full_pipeline_production_deploy_20260518/cloudrun_deploy_execution_report.json",
        "decision_path": ["decision"],
        "ok_path": ["ok"],
    },
    {
        "id": "cloudrun_stage7_smoke",
        "path": "reports/cloudrun_stage7_production_smoke_20260518/cloudrun_stage7_production_smoke.json",
        "decision_path": ["decision"],
        "ok_path": ["ok"],
    },
    {
        "id": "cloudrun_weekly_smoke",
        "path": "reports/cloudrun_weekly_production_smoke_20260518/cloudrun_weekly_production_smoke.json",
        "decision_path": ["decision"],
        "ok_path": ["ok"],
    },
    {
        "id": "miniprogram_upload",
        "path": "reports/miniprogram_upload_20260518/miniprogram_upload_execution_report.json",
        "decision_path": ["decision"],
        "ok_path": ["ok"],
    },
    {
        "id": "miniprogram_review_boundary",
        "path": "reports/miniprogram_review_submission_boundary_20260518/miniprogram_review_submission_boundary.json",
        "decision_path": ["decision"],
        "ok_path": ["ok"],
    },
    {
        "id": "production_sqlite_surface",
        "path": "reports/production_sqlite_surface_decision_20260518/production_sqlite_surface_decision.json",
        "decision_path": ["decision"],
        "ok_path": ["ok"],
    },
    {
        "id": "ocr_md_deepseek_contract",
        "path": "reports/ocr_md_deepseek_contract_audit_20260518/ocr_md_deepseek_contract_audit.json",
        "decision_path": ["decision"],
        "ok_path": ["ok"],
    },
    {
        "id": "vector_router",
        "path": "reports/vector_collection_router_smoke_20260518/vector_collection_router_smoke.json",
        "decision_path": ["decision"],
        "ok_path": ["ok"],
    },
    {
        "id": "graph_rag_recommendation",
        "path": "reports/graph_rag_recommendation_current_smoke_20260518/graph_rag_recommendation_current_smoke.json",
        "decision_path": ["decision"],
        "ok_path": ["ok"],
    },
    {
        "id": "qdrant_stage7_alias",
        "path": "reports/qdrant_alias_promote_qwen3_20260514/qdrant_alias_promote_report.json",
        "decision_path": ["schema_version"],
        "ok_path": ["applied"],
    },
    {
        "id": "qdrant_poster_staging",
        "path": "reports/poster_vector_write_gate_packet_wave01_07_20260518/poster_vector_write_gate_packet.json",
        "decision_path": ["poster_staging_evidence", "decision"],
        "ok_path": ["poster_staging_evidence", "ok"],
    },
    {
        "id": "neo4j_ocr_entity_staging",
        "path": "reports/ocr_entity_merge_write_gate_packet_wave01_07_20260518/ocr_entity_merge_write_gate_packet.json",
        "decision_path": ["decision"],
        "ok_path": ["ok"],
    },
    {
        "id": "graph_production_verify",
        "path": "reports/graph_production_promotion_verify_20260517/promotion_report.json",
        "decision_path": ["decision"],
        "ok_path": ["ok"],
    },
    {
        "id": "mem0_local_canary",
        "path": "reports/mem0_local_write_read_canary_20260518/mem0_local_write_read_canary.json",
        "decision_path": ["decision"],
        "ok_path": ["ok"],
    },
    {
        "id": "dajiala_roi",
        "path": "reports/dajiala_roi_budget_gate_packet_20260518/dajiala_roi_budget_gate_packet.json",
        "decision_path": ["decision"],
        "ok_path": ["ok"],
    },
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def to_rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        try:
            return path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return str(path)


def resolve(path_text: str | Path) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def nested_get(payload: dict[str, Any], keys: list[str]) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def should_scan_doc(path: Path) -> bool:
    parts = set(path.relative_to(ROOT).parts)
    return not bool(parts & DOC_EXCLUDE_PARTS)


def classify_doc(rel: str) -> str:
    upper = rel.upper()
    if rel in AUTHORITY_ORDER:
        return "authority"
    if rel.startswith("prds/"):
        return "prd"
    if rel.startswith("docs_archive/"):
        return "historical_archive"
    if rel.startswith("docs/"):
        return "current_docs"
    if any(token in upper for token in ["PLAN", "DESIGN", "ARCH", "RUNBOOK", "SSOT", "GATE", "VISION"]):
        return "design_plan"
    if any(token in upper for token in ["HANDOFF", "REPORT", "AUDIT", "TODO"]):
        return "handoff_or_audit"
    return "reference"


def scan_docs() -> dict[str, Any]:
    docs: list[dict[str, Any]] = []
    by_category: Counter[str] = Counter()
    by_top_dir: Counter[str] = Counter()
    authority_present: list[dict[str, Any]] = []
    missing_authority = []

    for rel in AUTHORITY_ORDER:
        path = ROOT / rel
        if path.exists():
            authority_present.append({"path": rel, "rank": AUTHORITY_ORDER.index(rel) + 1})
        else:
            missing_authority.append(rel)

    for path in sorted(ROOT.rglob("*.md"), key=lambda item: item.as_posix().lower()):
        if not should_scan_doc(path):
            continue
        rel = path.relative_to(ROOT).as_posix()
        category = classify_doc(rel)
        size = path.stat().st_size if path.exists() else 0
        by_category[category] += 1
        by_top_dir[rel.split("/")[0] if "/" in rel else "."] += 1
        docs.append(
            {
                "path": rel,
                "category": category,
                "bytes": size,
                "authority_rank": AUTHORITY_ORDER.index(rel) + 1 if rel in AUTHORITY_ORDER else None,
            }
        )

    current_design_docs = [
        item["path"]
        for item in docs
        if item["category"] in {"authority", "design_plan", "current_docs", "prd"}
    ]
    historical_docs = [
        item["path"]
        for item in docs
        if item["category"] in {"historical_archive", "handoff_or_audit", "reference"}
    ]
    return {
        "markdown_count": len(docs),
        "by_category": dict(sorted(by_category.items())),
        "by_top_dir": dict(sorted(by_top_dir.items())),
        "authority_present": authority_present,
        "authority_missing": missing_authority,
        "current_design_docs_sample": current_design_docs[:80],
        "historical_or_reference_sample": historical_docs[:80],
    }


def code_inventory() -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    by_lane: Counter[str] = Counter()
    missing: list[str] = []
    for item in CODE_ENTRYPOINTS:
        path = resolve(item["path"])
        exists = path.exists()
        by_lane[item["lane"]] += 1
        if not exists:
            missing.append(item["path"])
        entries.append(
            {
                "lane": item["lane"],
                "path": item["path"],
                "exists": exists,
                "role": item["role"],
            }
        )
    return {
        "entrypoint_count": len(entries),
        "by_lane": dict(sorted(by_lane.items())),
        "missing_entrypoints": missing,
        "entrypoints": entries,
    }


def evidence_registry() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    missing: list[str] = []
    for spec in EVIDENCE_SPECS:
        path = resolve(spec["path"])
        payload = read_json(path)
        exists = path.exists()
        if not exists:
            missing.append(spec["path"])
        items.append(
            {
                "id": spec["id"],
                "path": spec["path"],
                "exists": exists,
                "ok": bool(nested_get(payload, spec["ok_path"])) if payload else False,
                "decision": nested_get(payload, spec["decision_path"]) if payload else "",
                "generated_at": payload.get("generated_at", "") if payload else "",
                "writes": payload.get("writes", "") if payload else "",
            }
        )
    return {
        "evidence_count": len(items),
        "missing_evidence": missing,
        "items": items,
    }


def execution_surface_ledger() -> dict[str, Any]:
    deploy = read_json(ROOT / "reports/full_pipeline_production_deploy_20260518/cloudrun_deploy_execution_report.json")
    stage7_smoke = read_json(ROOT / "reports/cloudrun_stage7_production_smoke_20260518/cloudrun_stage7_production_smoke.json")
    weekly_smoke = read_json(ROOT / "reports/cloudrun_weekly_production_smoke_20260518/cloudrun_weekly_production_smoke.json")
    qdrant_alias = read_json(ROOT / "reports/qdrant_alias_promote_qwen3_20260514/qdrant_alias_promote_report.json")
    poster = read_json(ROOT / "reports/poster_vector_write_gate_packet_wave01_07_20260518/poster_vector_write_gate_packet.json")
    ocr_entity = read_json(ROOT / "reports/ocr_entity_merge_write_gate_packet_wave01_07_20260518/ocr_entity_merge_write_gate_packet.json")
    graph_verify = read_json(ROOT / "reports/graph_production_promotion_verify_20260517/promotion_report.json")
    mem0 = read_json(ROOT / "reports/mem0_local_write_read_canary_20260518/mem0_local_write_read_canary.json")
    roi = read_json(ROOT / "reports/dajiala_roi_budget_gate_packet_20260518/dajiala_roi_budget_gate_packet.json")
    operation = read_json(ROOT / "reports/full_pipeline_production_operation_packet_20260518/full_pipeline_production_operation_packet.json")
    dajiala_execution = read_json(
        ROOT / "reports/dajiala_paid_wave07_execution_packet_20260518/dajiala_paid_wave_execution_packet.json"
    )
    dajiala_archive = read_json(ROOT / "reports/dajiala_paid_wave07_archive_20260517/dajiala-repair-status.json")
    miniprogram_upload = read_json(ROOT / "reports/miniprogram_upload_20260518/miniprogram_upload_execution_report.json")
    miniprogram_review = read_json(
        ROOT / "reports/miniprogram_review_submission_boundary_20260518/miniprogram_review_submission_boundary.json"
    )
    sqlite_surface = read_json(
        ROOT / "reports/production_sqlite_surface_decision_20260518/production_sqlite_surface_decision.json"
    )
    dry_run_log = ROOT / "reports/full_pipeline_production_operation_packet_20260518/weekly_bake_and_deploy_dry_run.log"
    dajiala_total = int(dajiala_archive.get("totalItems") or 0)
    dajiala_succeeded = int(dajiala_archive.get("succeededCount") or 0)
    dajiala_success_rate = (dajiala_succeeded / dajiala_total) if dajiala_total else 0.0
    dajiala_completed = dajiala_archive.get("status") == "completed" and dajiala_total > 0

    surfaces = [
        {
            "surface": "cloudrun_weekly_api",
            "state": "executed_and_smoked",
            "executed": bool(nested_get(deploy, ["safety", "cloud_deploy_executed"])),
            "verified": bool(deploy.get("ok") and stage7_smoke.get("ok") and weekly_smoke.get("ok")),
            "evidence": [
                "reports/full_pipeline_production_deploy_20260518/cloudrun_deploy_execution_report.json",
                "reports/cloudrun_stage7_production_smoke_20260518/cloudrun_stage7_production_smoke.json",
                "reports/cloudrun_weekly_production_smoke_20260518/cloudrun_weekly_production_smoke.json",
            ],
        },
        {
            "surface": "weekly_miniprogram_bake",
            "state": "dry_run_verified",
            "executed": dry_run_log.exists(),
            "verified": dry_run_log.exists(),
            "evidence": ["reports/full_pipeline_production_operation_packet_20260518/weekly_bake_and_deploy_dry_run.log"],
        },
        {
            "surface": "qdrant_stage7_text_aliases",
            "state": "alias_applied",
            "executed": bool(qdrant_alias.get("applied")),
            "verified": bool(qdrant_alias.get("applied") and nested_get(qdrant_alias, ["validation", "collection_health"])),
            "evidence": ["reports/qdrant_alias_promote_qwen3_20260514/qdrant_alias_promote_report.json"],
        },
        {
            "surface": "qdrant_poster_text_staging",
            "state": "staging_write_verified",
            "executed": bool(nested_get(poster, ["poster_staging_evidence", "qdrant_write_executed"])),
            "verified": bool(nested_get(poster, ["poster_staging_evidence", "ok"])),
            "evidence": ["reports/poster_vector_write_gate_packet_wave01_07_20260518/poster_vector_write_gate_packet.json"],
        },
        {
            "surface": "neo4j_ocr_entity_staging",
            "state": "staging_write_verified",
            "executed": bool(nested_get(ocr_entity, ["safety", "neo4j_write_executed"])),
            "verified": bool(nested_get(ocr_entity, ["staging_apply_evidence", "verification", "ok"])),
            "evidence": ["reports/ocr_entity_merge_write_gate_packet_wave01_07_20260518/ocr_entity_merge_write_gate_packet.json"],
        },
        {
            "surface": "neo4j_stage7_production_labels",
            "state": "live_effect_verified_no_mutation_in_verify_run",
            "executed": False,
            "verified": bool(graph_verify.get("ok")),
            "evidence": ["reports/graph_production_promotion_verify_20260517/promotion_report.json"],
        },
        {
            "surface": "mem0_local_canary",
            "state": "local_write_read_verified",
            "executed": bool(nested_get(mem0, ["safety", "mem0_write_executed"])),
            "verified": bool(mem0.get("ok") and mem0.get("query_self_hit")),
            "evidence": ["reports/mem0_local_write_read_canary_20260518/mem0_local_write_read_canary.json"],
        },
        {
            "surface": "production_sqlite",
            "state": (
                "not_applicable_current_release_path"
                if sqlite_surface.get("decision") == "production_sqlite_not_applicable_to_current_selected_release_path"
                else "not_executed_runner_candidate_needs_design"
            ),
            "executed": False,
            "verified": bool(
                sqlite_surface.get("ok")
                and not bool(sqlite_surface.get("production_sqlite_execution_required_now"))
            ),
            "evidence": [
                "reports/production_sqlite_surface_decision_20260518/production_sqlite_surface_decision.json",
                operation.get("publish_target", {}).get("artifact_source", ""),
            ],
            "execution_required_now": bool(sqlite_surface.get("production_sqlite_execution_required_now")),
        },
        {
            "surface": "miniprogram_upload",
            "state": (
                "developer_version_upload_verified"
                if miniprogram_upload.get("ok")
                else "not_executed_manual_or_external_release_job"
            ),
            "executed": bool(nested_get(miniprogram_upload, ["safety", "miniprogram_upload_executed"])),
            "verified": bool(miniprogram_upload.get("ok")),
            "evidence": [
                "reports/miniprogram_upload_20260518/miniprogram_upload_execution_report.json",
                "reports/full_pipeline_production_operation_packet_20260518/full_pipeline_production_operation_packet.json",
            ],
            "review_submitted": bool(nested_get(miniprogram_upload, ["limits", "review_submitted"])),
        },
        {
            "surface": "miniprogram_review_submission",
            "state": (
                "manual_boundary_ready_not_submitted"
                if miniprogram_review.get("decision") == "miniprogram_review_submission_manual_boundary_ready"
                else "boundary_blocked_or_unknown"
            ),
            "executed": bool(nested_get(miniprogram_review, ["safety", "review_submit_executed"])),
            "verified": False,
            "evidence": [
                "reports/miniprogram_review_submission_boundary_20260518/miniprogram_review_submission_boundary.json"
            ],
            "manual_review_required": bool(
                nested_get(miniprogram_review, ["limits", "mp_console_manual_review_required"])
            ),
        },
        {
            "surface": "dajiala_wave07_paid",
            "state": (
                "executed_low_roi_success_rate_green_consumed"
                if dajiala_completed and dajiala_success_rate >= 0.30
                else "execution_packet_ready_not_completed"
                if dajiala_execution.get("decision") == "dajiala_paid_wave_execution_ready"
                else "blocked_by_roi_packet"
            ),
            "executed": dajiala_completed,
            "verified": dajiala_completed and dajiala_succeeded > 0,
            "evidence": [
                "reports/dajiala_paid_wave07_execution_packet_20260518/dajiala_paid_wave_execution_packet.json",
                "reports/dajiala_paid_wave07_archive_20260517/dajiala-repair-status.json",
                "reports/dajiala_roi_budget_gate_packet_20260518/dajiala_roi_budget_gate_packet.json",
            ],
            "allowed": bool(roi.get("next_paid_wave_allowed")),
            "total": dajiala_total,
            "succeeded": dajiala_succeeded,
            "success_rate": round(dajiala_success_rate, 4),
        },
    ]
    return {
        "surface_count": len(surfaces),
        "executed_count": sum(1 for item in surfaces if item.get("executed")),
        "verified_count": sum(1 for item in surfaces if item.get("verified")),
        "surfaces": surfaces,
    }


def load_status_summaries() -> dict[str, Any]:
    prd = read_json(ROOT / "reports/prd_longrun_status_20260518/prd_longrun_status.json")
    final = read_json(ROOT / "reports/final_full_pipeline_readiness_20260518/final_full_pipeline_readiness.json")
    roi = read_json(ROOT / "reports/dajiala_roi_budget_gate_packet_20260518/dajiala_roi_budget_gate_packet.json")
    weekly = read_json(ROOT / "reports/cloudrun_weekly_production_smoke_20260518/cloudrun_weekly_production_smoke.json")
    return {
        "prd_status": {
            "production_ready": prd.get("production_ready"),
            "blocked_prds": prd.get("blocked_prds") or [],
            "known_limitations": prd.get("known_limitations") or [],
            "total_prds": len(prd.get("prds") or []),
            "non_product_complete_prds": [
                item.get("id")
                for item in prd.get("prds") or []
                if not bool(item.get("production_ready"))
            ],
        },
        "final_readiness": {
            "decision": final.get("decision"),
            "full_pipeline_run_allowed": final.get("full_pipeline_run_allowed"),
            "release_ready_gates": final.get("release_ready_gates") or {},
        },
        "dajiala_roi": {
            "decision": roi.get("decision"),
            "next_paid_wave_allowed": roi.get("next_paid_wave_allowed"),
            "known_unconsumed_queue_rows": nested_get(roi, ["roi_metrics", "known_unconsumed_queue_rows"])
            or nested_get(roi, ["current_status", "known_unconsumed_queue_rows"])
            or nested_get(roi, ["dajiala", "known_unconsumed_queue_rows"]),
            "hard_gates_remaining": roi.get("hard_gates_remaining") or [],
        },
        "weekly_smoke": {
            "decision": weekly.get("decision"),
            "warnings": weekly.get("warnings") or [],
        },
    }


def decisions(status: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": "full_pipeline_ready_not_all_prds_product_complete",
            "decision": "Current selected full pipeline is production-ready, but non-production-ready PRDs remain staging/report/deferred work.",
            "basis": [
                f"blocked_prds={status['prd_status']['blocked_prds']}",
                f"non_product_complete_prds={status['prd_status']['non_product_complete_prds']}",
            ],
        },
        {
            "id": "runner_evidence_over_authorization",
            "decision": "Authorization packets open gates, but each production/write surface needs its own runner evidence before it is called complete.",
            "basis": [
                "CloudRun deploy has dedicated execution evidence.",
                "Miniprogram developer-version upload has dedicated execution evidence.",
                "Production SQLite has a current-release-path decision packet and no write target for the selected JSON/API lane.",
                "Miniprogram review submission/public release remains unexecuted because the current local runner exposes no submit-audit/release command.",
            ],
        },
        {
            "id": "ocr_before_deepseek",
            "decision": "DeepSeek stays a text lane; image evidence must enter through OCR before Markdown/DeepSeek input.",
            "basis": [
                "Existing paid Dajiala wave01-06 OCR contract audit is green.",
                "No new paid rerun is justified only for the image-blind-spot concern.",
            ],
        },
        {
            "id": "dajiala_cost_stop",
            "decision": "Do not start wave07 from stale paid permission; the current ROI packet blocks it until a fresh cap/balance/signed-link gate exists.",
            "basis": [
                f"roi_decision={status['dajiala_roi']['decision']}",
                f"next_paid_wave_allowed={status['dajiala_roi']['next_paid_wave_allowed']}",
            ],
        },
        {
            "id": "ldr_candidate_only",
            "decision": "local-deep-research remains candidate research and contradiction checking, not a direct production writer.",
            "basis": ["SSOT and integration plan mark LDR as read-only/candidate-only."],
        },
    ]


def execution_plan(status: dict[str, Any], ledger: dict[str, Any]) -> list[dict[str, Any]]:
    sqlite_surface = next(item for item in ledger["surfaces"] if item["surface"] == "production_sqlite")
    upload_surface = next(item for item in ledger["surfaces"] if item["surface"] == "miniprogram_upload")
    review_surface = next(item for item in ledger["surfaces"] if item["surface"] == "miniprogram_review_submission")
    return [
        {
            "step": "refresh_operation_packet_with_weekly_dry_run_log",
            "mode": "report_refresh",
            "allowed_now": True,
            "done_when": "operation packet records the existing weekly bake dry-run log",
        },
        {
            "step": "run_stage7_safe_handoff_verify",
            "mode": "verification",
            "allowed_now": True,
            "done_when": "targeted tests, compile, CloudRun Stage7 tests, report existence, and service checks pass",
        },
        {
            "step": "keep_cloudrun_weekly_api_monitored",
            "mode": "read_only_smoke",
            "allowed_now": True,
            "done_when": "Stage7 and weekly production smoke stay green",
        },
        {
            "step": "keep_production_sqlite_as_noop_for_current_json_api_release_path",
            "mode": "decision_evidence",
            "allowed_now": sqlite_surface["verified"],
            "done_when": "production SQLite surface packet says no current release-path SQLite write target exists",
        },
        {
            "step": "submit_miniprogram_review_outside_current_local_runner",
            "mode": "external_manual_boundary",
            "allowed_now": bool(upload_surface["verified"]) and bool(review_surface["manual_review_required"]),
            "done_when": "mp.weixin.qq.com review submission and later public release are verified by a separate account-side evidence packet",
        },
        {
            "step": "hold_dajiala_wave07",
            "mode": "cost_guard",
            "allowed_now": not bool(status["dajiala_roi"]["next_paid_wave_allowed"]),
            "done_when": "fresh ROI packet sets a spend cap, checks balance without printing secrets, and selects signed long-link rows",
        },
    ]


def build_report(out_dir: Path) -> dict[str, Any]:
    docs = scan_docs()
    code = code_inventory()
    evidence = evidence_registry()
    ledger = execution_surface_ledger()
    status = load_status_summaries()
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": not docs["authority_missing"] and not code["missing_entrypoints"] and not evidence["missing_evidence"],
        "authority": {
            "order": AUTHORITY_ORDER,
            "present": docs["authority_present"],
            "missing": docs["authority_missing"],
        },
        "doc_inventory": docs,
        "code_inventory": code,
        "evidence_registry": evidence,
        "execution_surface_ledger": ledger,
        "current_status": status,
        "decisions": decisions(status),
        "execution_plan": execution_plan(status, ledger),
        "safety": {
            "paid_api_called": False,
            "production_publish_executed": False,
            "production_sqlite_write_executed": False,
            "qdrant_write_executed_by_this_script": False,
            "neo4j_write_executed_by_this_script": False,
            "mem0_write_executed_by_this_script": False,
            "d_scan_executed": False,
            "secret_value_read_or_printed": False,
            "reports_only": True,
        },
        "writes": "report_only_integrated_plan",
    }
    write_json(out_dir / "stage7_integrated_design_execution_plan.json", report)
    write_markdown(out_dir / "stage7_integrated_design_execution_plan.md", report)
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Integrated Design Execution Plan",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- schema_version: `{report['schema_version']}`",
        "",
        "## Authority",
        "",
    ]
    for item in report["authority"]["present"]:
        lines.append(f"- rank `{item['rank']}`: `{item['path']}`")
    if report["authority"]["missing"]:
        lines.append("")
        lines.append("Missing authority files:")
        lines.extend(f"- `{item}`" for item in report["authority"]["missing"])

    lines.extend(
        [
            "",
            "## Document Inventory",
            "",
            f"- markdown_count: `{report['doc_inventory']['markdown_count']}`",
        ]
    )
    for key, value in report["doc_inventory"]["by_category"].items():
        lines.append(f"- {key}: `{value}`")

    lines.extend(
        [
            "",
            "## Code Entrypoints",
            "",
            f"- entrypoint_count: `{report['code_inventory']['entrypoint_count']}`",
        ]
    )
    for key, value in report["code_inventory"]["by_lane"].items():
        lines.append(f"- {key}: `{value}`")
    if report["code_inventory"]["missing_entrypoints"]:
        lines.append("")
        lines.append("Missing entrypoints:")
        lines.extend(f"- `{item}`" for item in report["code_inventory"]["missing_entrypoints"])

    lines.extend(["", "## Execution Surface Ledger", ""])
    for item in report["execution_surface_ledger"]["surfaces"]:
        lines.append(
            f"- `{item['surface']}`: state=`{item['state']}`, "
            f"executed=`{item['executed']}`, verified=`{item['verified']}`"
        )

    lines.extend(["", "## Decisions", ""])
    for item in report["decisions"]:
        lines.append(f"### {item['id']}")
        lines.append(f"- decision: {item['decision']}")
        for basis in item["basis"]:
            lines.append(f"- basis: {basis}")
        lines.append("")

    lines.extend(["## Execution Plan", ""])
    for index, item in enumerate(report["execution_plan"], start=1):
        lines.append(
            f"{index}. `{item['step']}` mode=`{item['mode']}` "
            f"allowed_now=`{item['allowed_now']}`"
        )
        lines.append(f"   done_when: {item['done_when']}")

    lines.extend(["", "## Safety", ""])
    lines.append(
        "- This script only writes the integrated plan report. It does not deploy, publish, call paid APIs, scan D:, read secrets, or mutate Qdrant/Neo4j/mem0."
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(args.out_dir)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "markdown_count": report["doc_inventory"]["markdown_count"],
                "entrypoint_count": report["code_inventory"]["entrypoint_count"],
                "evidence_count": report["evidence_registry"]["evidence_count"],
                "executed_surfaces": report["execution_surface_ledger"]["executed_count"],
                "verified_surfaces": report["execution_surface_ledger"]["verified_count"],
                "report": str(args.out_dir / "stage7_integrated_design_execution_plan.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
