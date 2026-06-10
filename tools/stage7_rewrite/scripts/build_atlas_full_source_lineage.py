#!/usr/bin/env python3
"""Build the atlas full source lineage packet from scripts and reports.

Read-only production-readiness step for the China underground electronic music
atlas. It reverse-maps the current 47k marker, 93k/FULL_MAP lineage, V6/OCR
repairs, Dajiala paid repair waves, external identity evidence, and vector
staging from bounded local scripts/reports. It records D: references that appear
in scripts, but never scans or opens D: paths.
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


PROJECT_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS = STAGE7_ROOT / "reports"
DEFAULT_OUT_DIR = REPORTS / "atlas_full_source_lineage_47k_93k_gap_20260519"
SCHEMA_VERSION = "atlas_full_source_lineage.v1"

DEFAULT_SCRIPT_ROOTS = (
    "scripts",
    "src",
    "services",
    "tools/stage7_rewrite/scripts",
    "tools/stage7_rewrite/prefect",
    "tools/stage7_rewrite/stage7",
)

SCRIPT_SUFFIXES = {".py", ".ps1", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".json"}
SKIP_DIR_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "genericagent-chinese.backup-dirty-copy-20260505_124638",
    "genericagent-chinese-upstream-20260505_123433",
    "genericagent-upstream-current-20260506_212303",
}
MAX_SCRIPT_BYTES = 2_000_000

REPORT_REF_RE = re.compile(r"reports[\\/][A-Za-z0-9_.@+=:,;(){}\[\]\-\\/]+")
WINDOWS_D_RE = re.compile(r"[Dd]:\\[^\s'\"`<>|]+")
MNT_D_RE = re.compile(r"/mnt/d/[^\s'\"`<>|]+")
KEYWORDS = (
    "47k",
    "93k",
    "full93k",
    "FULL_MAP",
    "FULL_MAP_SMART_BACKFILL_20260509",
    "SECOND_PASS_NEW_ASSETS_20260509",
    "WHERE_TO_RAVE_WECHAT_SYNC_20260508",
    "fullmap_47k",
    "v6_p1",
    "v6_image_bucket",
    "Dajiala",
    "dajiala",
    "stable_merge",
    "delta375",
    "LANGUAGE_FIELD_VECTOR",
    "vector_role",
    "qdrant",
    "maigret",
    "GraphCandidate",
    "external_identity",
    "local-deep-research",
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def count_jsonl(path: Path) -> int:
    if not path.exists() or path.stat().st_size > MAX_SCRIPT_BYTES * 10:
        return 0
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        return sum(1 for line in handle if line.strip())


def nested_get(data: dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


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


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def should_skip(path: Path) -> bool:
    lowered_parts = {part.lower() for part in path.parts}
    return bool(lowered_parts & {item.lower() for item in SKIP_DIR_PARTS})


def iter_script_files(project_root: Path, script_roots: list[Path] | None = None) -> list[Path]:
    roots = script_roots or [project_root / raw for raw in DEFAULT_SCRIPT_ROOTS]
    files: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if should_skip(path):
                continue
            try:
                is_file = path.is_file()
            except OSError:
                continue
            if not is_file or path.suffix.lower() not in SCRIPT_SUFFIXES:
                continue
            try:
                if path.stat().st_size > MAX_SCRIPT_BYTES:
                    continue
            except OSError:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append(path)
    return sorted(files, key=lambda item: str(item).lower())


def classify_family(value: str) -> str:
    lower = value.lower()
    if "weekly" in lower or "miniprogram" in lower or "cloudrun" in lower:
        return "weekly_downstream_consumer"
    if "local-deep-research" in lower or "ldr" in lower:
        return "local_deep_research_candidate"
    if "maigret" in lower or "external_identity" in lower or "external_evidence" in lower or "social" in lower:
        return "external_identity_network"
    if "vector" in lower or "qdrant" in lower or "language_field" in lower or "embed" in lower:
        return "vector_retrieval"
    if "dajiala" in lower or "paid" in lower:
        return "dajiala_paid_repair"
    if "v6_p1" in lower or "v6_image_bucket" in lower or "ocr_empty" in lower or "low_quality" in lower:
        return "v6_ocr_visual_repair"
    if "ocr" in lower or "markitdown" in lower or "deepseek" in lower or "flash" in lower:
        return "ocr_markdown_llm_extract"
    if "full_map" in value or "fullmap" in lower or "93k" in lower or "where_to_rave" in lower or "second_pass" in lower:
        return "fullmap_93k_source"
    if "47k" in lower or "stable_merge" in lower or "stage7_47" in lower or "delta375" in lower:
        return "current_47k_production_base"
    return "other"


def classify_kind(value: str) -> str:
    if WINDOWS_D_RE.search(value) or MNT_D_RE.search(value):
        return "d_path_reference_recorded_not_scanned"
    if "reports" in value.lower():
        return "report_reference"
    return "keyword_reference"


def extract_script_references(project_root: Path, script_roots: list[Path] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    script_files = iter_script_files(project_root, script_roots)
    for path in script_files:
        text = safe_read_text(path)
        if not text:
            continue
        script_rel = rel(path, project_root)
        for line_no, line in enumerate(text.splitlines(), start=1):
            refs: list[str] = []
            refs.extend(match.group(0).rstrip("),];}") for match in REPORT_REF_RE.finditer(line))
            refs.extend(match.group(0).rstrip("),];}") for match in WINDOWS_D_RE.finditer(line))
            refs.extend(match.group(0).rstrip("),];}") for match in MNT_D_RE.finditer(line))
            for keyword in KEYWORDS:
                if keyword in line:
                    refs.append(keyword)
            for ref in sorted(set(refs)):
                rows.append(
                    {
                        "script": script_rel,
                        "line": line_no,
                        "reference": ref,
                        "kind": classify_kind(ref),
                        "family": classify_family(ref),
                    }
                )
    by_family = Counter(row["family"] for row in rows)
    by_kind = Counter(row["kind"] for row in rows)
    summary = {
        "script_files_scanned": len(script_files),
        "reference_count": len(rows),
        "by_family": dict(sorted(by_family.items())),
        "by_kind": dict(sorted(by_kind.items())),
        "d_path_references_recorded_not_scanned": by_kind.get("d_path_reference_recorded_not_scanned", 0),
    }
    return rows, summary


def artifact_exists(stage7_root: Path, rel_path: str) -> bool:
    return (stage7_root / rel_path).exists()


def file_signal(stage7_root: Path, rel_path: str) -> dict[str, Any]:
    path = stage7_root / rel_path
    return {
        "path": rel_path,
        "exists": path.exists(),
        "bytes": path.stat().st_size if path.exists() and path.is_file() else None,
    }


def load_report(stage7_root: Path, rel_path: str) -> dict[str, Any]:
    return read_json(stage7_root / rel_path)


def build_source_layers(stage7_root: Path) -> list[dict[str, Any]]:
    stable = load_report(
        stage7_root,
        "reports/stable_merge_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518/stable_merge_summary.json",
    )
    promotion = load_report(
        stage7_root,
        "reports/graph_production_promotion_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_verify_20260518/promotion_report.json",
    )
    gap = load_report(stage7_root, "reports/stage7_data_completeness_gap_ledger_20260518/gap_ledger.json")
    gap_summary = gap.get("summary") if isinstance(gap.get("summary"), dict) else {}
    v6_merge = load_report(stage7_root, "reports/v6_47k_merge_readiness_packet_20260518/v6_47k_merge_readiness_packet.json")
    fullmap = load_report(stage7_root, "reports/pipeline_status_93k_live_reconcile_20260517/pipeline_status_93k_live_reconcile.json")
    artifact_rounds = load_report(
        stage7_root,
        "reports/stage7_graph_artifact_rounds_reconciliation_20260518/graph_artifact_rounds_reconciliation.json",
    )
    vector_sequence = load_report(
        stage7_root,
        "reports/vector_role_full_wave_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518/_sequence_status/sequence_status.json",
    )
    vector_role_report_root = (
        stage7_root / "reports" / "vector_role_full_wave_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518"
    )
    expected_vector_roles = ("multilingual_baseline", "ocr_baseline", "english_sidecar", "snowflake_canary")
    vector_role_reports_found = [
        role
        for role in expected_vector_roles
        if (vector_role_report_root / role / "qdrant_vector_role_full_wave_report.json").exists()
    ]
    vector_smoke = load_report(
        stage7_root,
        "reports/vector_collection_router_smoke_47k_delta375_roles_20260519/vector_collection_router_smoke.json",
    )
    alias_gate = load_report(stage7_root, "reports/qdrant_role_alias_gate_47k_delta375_20260519/qdrant_role_alias_gate.json")
    external_review = load_report(
        stage7_root,
        "reports/external_identity_source_followup_review_gate_47k_delta375_20260519/source_followup_review_gate_summary.json",
    )
    source_context = load_report(
        stage7_root,
        "reports/external_identity_source_context_recovery_47k_delta375_20260519/source_context_recovery_summary.json",
    )

    promotion_counts = promotion.get("after_counts") if isinstance(promotion.get("after_counts"), dict) else {}
    dajiala_totals = artifact_rounds.get("dajiala_totals") if isinstance(artifact_rounds.get("dajiala_totals"), dict) else {}
    stable_source_counts = stable.get("source_counts") if isinstance(stable.get("source_counts"), dict) else {}
    stable_lane_counts = stable.get("lane_counts") if isinstance(stable.get("lane_counts"), dict) else {}
    fullmap_data = fullmap.get("fullmap") if isinstance(fullmap.get("fullmap"), dict) else {}
    v6_residual = v6_merge.get("p1_residual") if isinstance(v6_merge.get("p1_residual"), dict) else {}

    return [
        {
            "source_id": "current_47k_text_graph_baseline",
            "family": "current_47k_production_base",
            "state": "complete_in_production_graph",
            "count_signal": int(gap_summary.get("current_text_graph_articles") or stable_lane_counts.get("unknown") or 0),
            "decision": "Keep as the historical 47k text graph baseline inside the expanded atlas marker.",
            "evidence": [
                file_signal(stage7_root, "reports/stage7_data_completeness_gap_ledger_20260518/gap_ledger.json"),
                file_signal(
                    stage7_root,
                    "reports/production_graph_source_lane_audit_20260518/source_lane_audit.json",
                ),
            ],
        },
        {
            "source_id": "v6_p1_ocr_markdown_visual_repair",
            "family": "v6_ocr_visual_repair",
            "state": "complete_in_production_graph",
            "count_signal": int(gap_summary.get("p1_merge_ready_articles_promoted") or 0),
            "decision": "The strict P1 OCR/Markdown/Flash repair rows are already promoted; do not rerun them.",
            "evidence": [
                file_signal(stage7_root, "reports/v6_47k_merge_readiness_packet_20260518/v6_47k_merge_readiness_packet.json"),
                file_signal(
                    stage7_root,
                    "reports/graph_production_promotion_v6_p1_ocr_markdown_flash_full1082_verify_20260518/promotion_report.json",
                ),
                file_signal(
                    stage7_root,
                    "reports/graph_production_promotion_v6_p1_local_ocr_flash_incremental_287_verify_20260518/promotion_report.json",
                ),
                file_signal(
                    stage7_root,
                    "reports/graph_production_promotion_v6_p1_local_ocr_second_pass_flash_incremental_28_verify_20260518/promotion_report.json",
                ),
            ],
        },
        {
            "source_id": "paid_dajiala_wave09_21_delta375_repair",
            "family": "dajiala_paid_repair",
            "state": "complete_in_current_47340_marker",
            "count_signal": int(stable_source_counts.get("dajiala_paid_wave09_21_ocr_markdown_flash_20260518") or 0),
            "decision": "The verified local OCR wave09-21 delta is consumed by the current graph marker; do not start a duplicate paid runner.",
            "evidence": [
                file_signal(
                    stage7_root,
                    "reports/ocr_markitdown_flash_reprocess_plan_wave09_21_delta_20260518/delta_manifest_summary.json",
                ),
                file_signal(
                    stage7_root,
                    "reports/ocr_markdown_flash_wave09_21_delta375_stable_extract_20260518/stable_materialize_summary.json",
                ),
                file_signal(
                    stage7_root,
                    "reports/graph_production_promotion_ocr_markdown_flash_wave09_21_delta375_verify_20260518/promotion_report.json",
                ),
            ],
        },
        {
            "source_id": "current_47340_atlas_graph_marker",
            "family": "current_47k_production_base",
            "state": "current_production_marker",
            "count_signal": int(stable.get("articles") or nested_get(promotion_counts, ("article", "promoted"), 0) or 0),
            "decision": "This is the current atlas data base for production-readiness work.",
            "counts": {
                "articles": nested_get(promotion_counts, ("article", "promoted"), stable.get("articles")),
                "entities": nested_get(promotion_counts, ("entity", "promoted")),
                "events": nested_get(promotion_counts, ("event", "promoted")),
                "promotion_run_id": promotion.get("promotion_run_id"),
                "promotion_verified": promotion.get("ok") is True,
            },
            "evidence": [
                file_signal(
                    stage7_root,
                    "reports/stable_merge_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518/stable_merge_summary.json",
                ),
                file_signal(
                    stage7_root,
                    "reports/graph_production_promotion_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_verify_20260518/promotion_report.json",
                ),
            ],
        },
        {
            "source_id": "fullmap_93k_extraction_lineage",
            "family": "fullmap_93k_source",
            "state": "green_upstream_lineage_not_extra_graph_promotion",
            "count_signal": int(fullmap_data.get("rows") or fullmap_data.get("selected_total") or 0),
            "decision": "93k/FULL_MAP is a green upstream/source lineage; it is not an automatic additional graph-promotion layer beyond the current marker.",
            "counts": {
                "complete": fullmap_data.get("complete"),
                "failed_total": fullmap_data.get("failed_total"),
                "pending_total": fullmap_data.get("pending_total"),
                "quality_verdict": nested_get(fullmap, ("quality", "verdict")),
            },
            "evidence": [
                file_signal(stage7_root, "reports/pipeline_status_93k_live_reconcile_20260517/pipeline_status_93k_live_reconcile.json"),
                {"path": "memory:WHERE_TO_RAVE/FULL_MAP/SECOND_PASS handoff", "exists": True, "bytes": None},
            ],
        },
        {
            "source_id": "full_v6_81417_structured_candidate",
            "family": "v6_ocr_visual_repair",
            "state": "candidate_only_not_promoted",
            "count_signal": int(gap_summary.get("v6_structured_rows") or 0),
            "decision": "Full V6 stays candidate-only until merge-readiness and source evidence prove a smaller promoted slice.",
            "counts": {
                "text_only_flash_rows": gap_summary.get("v6_image_bucket_rows_text_only_flash"),
                "p2_flash_quality_reextract_needed": next_gap_value(gap, "v6_image_bucket_visual_loss", "p2_flash_quality_reextract_needed"),
                "p3_event_missing_review": next_gap_value(gap, "v6_image_bucket_visual_loss", "p3_accepted_but_event_missing_review"),
            },
            "evidence": [
                file_signal(stage7_root, "reports/stage7_data_completeness_gap_ledger_20260518/gap_ledger.json"),
                file_signal(stage7_root, "reports/v6_47k_merge_readiness_packet_20260518/v6_47k_merge_readiness_packet.json"),
            ],
        },
        {
            "source_id": "v6_p1_residual_gap_queue",
            "family": "v6_ocr_visual_repair",
            "state": "residual_gap_review_or_restrategy",
            "count_signal": int(v6_residual.get("low_quality_ocr_text_review_rows") or gap_summary.get("p1_low_quality_text_review_rows") or 0)
            + int(v6_residual.get("ocr_empty_rows") or gap_summary.get("p1_remaining_local_ocr_rerun_rows") or 0),
            "decision": "Do not auto-send residual OCR rows to Flash; split low-quality text review from OCR-empty rows.",
            "counts": {
                "low_quality_ocr_text_review_rows": v6_residual.get("low_quality_ocr_text_review_rows")
                or gap_summary.get("p1_low_quality_text_review_rows"),
                "ocr_empty_rows": v6_residual.get("ocr_empty_rows") or gap_summary.get("p1_remaining_local_ocr_rerun_rows"),
                "paid_recapture_needed_rows": v6_residual.get("paid_recapture_needed_rows") or gap_summary.get("p1_paid_recapture_needed_rows"),
            },
            "evidence": [
                file_signal(
                    stage7_root,
                    "reports/v6_p1_existing_ocr_locator_after_second_pass_20260518/v6_p1_existing_ocr_low_quality_text_review_needed.jsonl",
                ),
                file_signal(stage7_root, "reports/stage7_data_completeness_gap_ledger_20260518/gap_ledger.json"),
            ],
        },
        {
            "source_id": "dajiala_paid_round_inventory_and_remaining_gate",
            "family": "dajiala_paid_repair",
            "state": "inventory_ready_more_paid_blocked",
            "count_signal": int(dajiala_totals.get("archive_round_records") or 0),
            "decision": "Use already verified local OCR indexes first; another paid Dajiala wave requires a fresh ROI/downstream-consumption packet.",
            "counts": {
                "archive_total_items": dajiala_totals.get("archive_total_items"),
                "archive_succeeded_count": dajiala_totals.get("archive_succeeded_count"),
                "archive_failed_count": dajiala_totals.get("archive_failed_count"),
                "verified_wave01_21_records": dajiala_totals.get("verified_wave01_21_records"),
                "wave09_21_graph_promoted": dajiala_totals.get("wave09_21_graph_promoted"),
            },
            "evidence": [
                file_signal(
                    stage7_root,
                    "reports/stage7_graph_artifact_rounds_reconciliation_20260518/graph_artifact_rounds_reconciliation.json",
                ),
                file_signal(stage7_root, "reports/dajiala_roi_budget_gate_packet_superlongrun_20260518/dajiala_roi_budget_gate_packet.json"),
            ],
        },
        {
            "source_id": "external_identity_network_media_queue",
            "family": "external_identity_network",
            "state": "reviewed_no_graph_edges",
            "count_signal": int(external_review.get("reviewed_rows") or 0),
            "decision": "Network/media/profile evidence remains report-only; accepted graph edges are zero.",
            "counts": {
                "rejected_rows": external_review.get("rejected_rows"),
                "needs_more_source_rows": external_review.get("needs_more_source_rows"),
                "candidate_direct_text_rows": external_review.get("candidate_direct_text_rows"),
                "source_context_input_rows": source_context.get("input_rows"),
                "rows_with_recovered_subject_candidates": source_context.get("rows_with_recovered_subject_candidates"),
                "accepted_for_graph": source_context.get("accepted_for_graph", 0),
            },
            "evidence": [
                file_signal(
                    stage7_root,
                    "reports/external_identity_source_followup_review_gate_47k_delta375_20260519/source_followup_review_gate_summary.json",
                ),
                file_signal(
                    stage7_root,
                    "reports/external_identity_source_context_recovery_47k_delta375_20260519/source_context_recovery_summary.json",
                ),
            ],
        },
        {
            "source_id": "role_isolated_vector_staging",
            "family": "vector_retrieval",
            "state": "staging_complete_alias_apply_gated",
            "count_signal": max(len(vector_sequence.get("completed_roles") or []), len(vector_role_reports_found)),
            "decision": "Vector staging is complete, but production serving alias apply is a separate explicit gate.",
            "counts": {
                "completed_roles": vector_sequence.get("completed_roles"),
                "role_reports_found": vector_role_reports_found,
                "sequence_decision": vector_sequence.get("decision"),
                "router_smoke_decision": vector_smoke.get("decision"),
                "alias_gate_decision": alias_gate.get("decision"),
                "alias_hard_gates_remaining": alias_gate.get("hard_gates_remaining"),
            },
            "evidence": [
                file_signal(
                    stage7_root,
                    "reports/vector_role_full_wave_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518/_sequence_status/sequence_status.json",
                ),
                file_signal(stage7_root, "reports/vector_collection_router_smoke_47k_delta375_roles_20260519/vector_collection_router_smoke.json"),
                file_signal(stage7_root, "reports/qdrant_role_alias_gate_47k_delta375_20260519/qdrant_role_alias_gate.json"),
            ],
        },
    ]


def next_gap_value(gap: dict[str, Any], gap_id: str, key: str) -> Any:
    for item in gap.get("gap_items") or []:
        if isinstance(item, dict) and item.get("gap_id") == gap_id:
            return item.get(key)
    return None


def build_decision_table(layers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for layer in layers:
        state = str(layer.get("state") or "")
        if state in {"current_production_marker", "complete_in_current_47340_marker", "complete_in_production_graph"}:
            action = "use_current_artifact_no_rerun"
        elif state.startswith("green_upstream"):
            action = "keep_as_source_lineage_not_direct_promotion"
        elif "candidate" in state:
            action = "hold_candidate_until_merge_readiness"
        elif "residual" in state:
            action = "split_review_queue_before_any_rerun"
        elif "blocked" in state or "gated" in state:
            action = "require_explicit_gate_packet"
        else:
            action = "review_before_production"
        rows.append(
            {
                "source_id": layer["source_id"],
                "family": layer["family"],
                "state": state,
                "count_signal": layer.get("count_signal"),
                "production_action": action,
                "decision": layer.get("decision"),
            }
        )
    return rows


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["script_reference_summary"]
    lines = [
        "# Atlas Full Source Lineage 47k + 93k + Gap",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- project_root: `{report['project_root']}`",
        "",
        "## Script-Derived Source References",
        "",
        f"- scanned script/config files: `{summary['script_files_scanned']}`",
        f"- source references found: `{summary['reference_count']}`",
        f"- D:/mnt/d references recorded, not scanned: `{summary['d_path_references_recorded_not_scanned']}`",
        "",
        "Family counts:",
        "",
    ]
    for family, count in summary["by_family"].items():
        lines.append(f"- `{family}`: `{count}`")

    lines.extend(
        [
            "",
            "## Production Decision Table",
            "",
            "| Source | Family | State | Count | Production action |",
            "| --- | --- | --- | ---: | --- |",
        ]
    )
    for row in report["production_decision_table"]:
        lines.append(
            "| `{source_id}` | `{family}` | `{state}` | {count} | `{action}` |".format(
                source_id=row["source_id"],
                family=row["family"],
                state=row["state"],
                count=row.get("count_signal") if row.get("count_signal") is not None else "",
                action=row["production_action"],
            )
        )

    lines.extend(["", "## Source Layer Decisions", ""])
    for layer in report["source_layers"]:
        lines.append(f"### {layer['source_id']}")
        lines.append("")
        lines.append(f"- family: `{layer['family']}`")
        lines.append(f"- state: `{layer['state']}`")
        lines.append(f"- count_signal: `{layer.get('count_signal')}`")
        lines.append(f"- decision: {layer['decision']}")
        counts = layer.get("counts")
        if isinstance(counts, dict) and counts:
            lines.append("- counts:")
            for key, value in counts.items():
                lines.append(f"  - `{key}`: `{value}`")
        lines.append("")

    lines.extend(["## Next Order", ""])
    for idx, item in enumerate(report["next_order"], start=1):
        lines.append(f"{idx}. {item}")

    lines.extend(["", "## Safety", ""])
    for key, value in report["safety"].items():
        lines.append(f"- `{key}`: `{value}`")
    return "\n".join(lines).rstrip() + "\n"


def build_lineage(
    project_root: Path = PROJECT_ROOT,
    stage7_root: Path | None = None,
    out_dir: Path | None = None,
    script_roots: list[Path] | None = None,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    stage7_root = (stage7_root or project_root / "tools" / "stage7_rewrite").resolve()
    out_dir = (out_dir or stage7_root / "reports" / DEFAULT_OUT_DIR.name).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    script_refs, script_summary = extract_script_references(project_root, script_roots)
    layers = build_source_layers(stage7_root)
    decision_table = build_decision_table(layers)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "project_root": str(project_root),
        "stage7_root": str(stage7_root),
        "decision": "atlas_full_source_lineage_ready_report_only",
        "source_layers": layers,
        "production_decision_table": decision_table,
        "script_reference_summary": script_summary,
        "outputs": {
            "json": str(out_dir / "atlas_full_source_lineage.json"),
            "markdown": str(out_dir / "atlas_full_source_lineage.md"),
            "script_references": str(out_dir / "script_path_references.jsonl"),
            "production_decision_table": str(out_dir / "production_source_decision_table.jsonl"),
        },
        "next_order": [
            "Use the 47,340 current graph marker as the production base for the atlas line.",
            "Treat 93k/FULL_MAP as green upstream lineage and evidence source, not an extra blind graph promotion.",
            "Keep full V6 81,417 rows candidate-only; promote only smaller merge-ready slices with proof.",
            "Split residual P1 OCR debt into 99 low-quality text review rows and 30 OCR-empty rows before any rerun.",
            "Do not pay Dajiala again until the remaining queue has a fresh ROI, no-duplicate, and downstream-consumption packet.",
            "Keep external identity edges at zero until direct source/profile proof passes strict review.",
            "Keep vector aliases report-only until an explicit apply token, rollback packet, and post-apply smoke exist.",
        ],
        "safety": {
            "report_only": True,
            "d_path_references_recorded_not_scanned": script_summary["d_path_references_recorded_not_scanned"],
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
    write_json(out_dir / "atlas_full_source_lineage.json", report)
    write_text(out_dir / "atlas_full_source_lineage.md", render_markdown(report))
    write_jsonl(out_dir / "script_path_references.jsonl", script_refs)
    write_jsonl(out_dir / "production_source_decision_table.jsonl", decision_table)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--stage7-root", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_lineage(args.project_root, args.stage7_root, args.out_dir)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "source_layers": len(report["source_layers"]),
                "script_files_scanned": report["script_reference_summary"]["script_files_scanned"],
                "reference_count": report["script_reference_summary"]["reference_count"],
                "d_path_references_recorded_not_scanned": report["script_reference_summary"][
                    "d_path_references_recorded_not_scanned"
                ],
                "report": report["outputs"]["json"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
