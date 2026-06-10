#!/usr/bin/env python3
"""Roll up DJ-first completion coverage after the sidecar overlay lane.

This is a report-only audit. It consumes existing redacted/report-local
artifacts, computes the current DJ completion effect and remaining work orders,
and does not open or mutate source/raw DBs, serving DBs, graph/vector stores,
public pointers, or remote services.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_COMPLETION_SUMMARY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_dj_completion_effect_audit_t5_t6_20260526"
    / "dj_completion_effect_audit_summary.json"
)
DEFAULT_OVERLAY_ATTACH_SUMMARY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t6_sidecar_overlay_serving_attach_smoke_t5_t6_20260526"
    / "overlay_serving_attach_smoke_summary.json"
)
DEFAULT_OVERLAY_UI_SUMMARY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t6_sidecar_overlay_ui_integration_smoke_t5_t6_20260526"
    / "overlay_social_ui_integration_smoke_summary.json"
)
DEFAULT_OVERLAY_UI_CONTRACT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t6_sidecar_overlay_ui_integration_smoke_t5_t6_20260526"
    / "overlay_social_ui_integration_contract.json"
)
DEFAULT_MANIFEST_VALIDATION_SUMMARY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t6_sidecar_manifest_validation_gate_t5_t6_20260526"
    / "sidecar_manifest_validation_summary.json"
)
DEFAULT_CURRENT_RUNTIME = REPO_ROOT / "docs" / "current-runtime.md"
DEFAULT_DOCUMENTATION_INDEX = REPO_ROOT / "docs" / "DOCUMENTATION_INDEX.md"
DEFAULT_THREADS_INDEX = REPO_ROOT / "docs" / "threads" / "THREADS_INDEX_20260522.md"
DEFAULT_CURRENT_CODE_MAP = REPO_ROOT / "docs" / "CURRENT_CODE_MAP.md"
DEFAULT_STAGE7_OVERLAY_SSOT = STAGE7_ROOT / "SSOT.md"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_dj_completion_overlay_rollup_t5_t6_20260527"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_T6_DJ_COMPLETION_OVERLAY_ROLLUP_20260527.md"
SCHEMA_VERSION = "stage7_atlas_dj_completion_overlay_rollup.v1"

URL_RE = re.compile(r"https?://|www\.", re.I)
SECRET_KEY_RE = re.compile(r"secret|token|cookie|password|api[_-]?key|authorization|bearer|pass_ticket|openid", re.I)
SECRET_VALUE_RE = re.compile(
    r"api[_-]?key\s*[:=]|authorization\s*[:=]|bearer\s+[A-Za-z0-9._-]{12,}|"
    r"pass_ticket=|openid=|token\s*[:=]|cookie\s*[:=]|password\s*[:=]",
    re.I,
)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)
WRITE_GUARD_KEYS = (
    "source_sqlite_write_executed",
    "serving_sqlite_write_executed",
    "serving_rebuild_executed",
    "neo4j_write_executed",
    "qdrant_write_executed",
    "public_pointer_updated",
    "huaidj_club_upload_executed",
    "memory_write_executed",
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 600) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def read_json(path: Path) -> Any:
    reject_d_root(path, "json_input")
    return json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))


def read_text_head(path: Path, limit: int = 20000) -> str:
    reject_d_root(path, "text_input")
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8-sig", errors="replace")[:limit]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def reject_d_root(path: Path, label: str) -> None:
    raw = str(path).replace("\\", "/").casefold()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"}:
        raise ValueError(f"{label} must not be an unbounded D: root: {path}")
    if raw.startswith("d:/ddownload") or raw.startswith("d:/aidata") or raw.startswith("/mnt/d/ddownload") or raw.startswith("/mnt/d/aidata"):
        raise ValueError(f"{label} must not scan cold D: data roots: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except Exception:
        return path.name


def artifact_ref(path: Path) -> dict[str, Any]:
    raw = str(path)
    return {
        "display": display_path(path),
        "basename": path.name,
        "exists": path.exists(),
        "bytes": path.stat().st_size if path.exists() and path.is_file() else 0,
        "path_sha256_12": hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:12],
    }


def int_at(payload: dict[str, Any], *keys: str) -> int:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return 0
        current = current.get(key)
    try:
        return int(current or 0)
    except (TypeError, ValueError):
        return 0


def field_metric(completion: dict[str, Any], table: str, field: str) -> dict[str, Any]:
    fields = completion.get("coverage", {}).get("candidate", {}).get(table, {}).get("fields", {})
    metric = fields.get(field, {})
    return {
        "non_empty": int(metric.get("non_empty") or 0),
        "missing": int(metric.get("missing") or 0),
        "pct": float(metric.get("pct") or 0.0),
    }


def summary_counts(completion: dict[str, Any]) -> dict[str, Any]:
    counts = completion.get("counts", {})
    candidate = counts.get("candidate", {})
    delta = counts.get("delta", {})
    return {
        "dj_profiles": int(candidate.get("dj_profile") or 0),
        "performance_events": int(candidate.get("performance_event") or 0),
        "dj_event_edges": int(candidate.get("dj_event") or 0),
        "directed_relations": int(candidate.get("dj_relation_rollup") or 0),
        "venue_rollups": int(candidate.get("dj_venue_rollup") or 0),
        "search_documents": int(candidate.get("search_document") or 0),
        "graph_windows": int(candidate.get("graph_window_cache") or 0),
        "delta_dj_profiles": int(delta.get("dj_profile") or 0),
        "delta_performance_events": int(delta.get("performance_event") or 0),
        "delta_dj_event_edges": int(delta.get("dj_event") or 0),
        "delta_directed_relations": int(delta.get("dj_relation_rollup") or 0),
        "delta_search_documents": int(delta.get("search_document") or 0),
        "delta_graph_windows": int(delta.get("graph_window_cache") or 0),
        "mapped_manual_candidate_rows": int(counts.get("mapped_manual_candidate_rows") or 0),
        "wsl_outlink_processed": int(counts.get("wsl_outlink_processed") or 0),
        "wsl_outlink_remaining": int(counts.get("wsl_outlink_remaining") or 0),
    }


def build_quality_snapshot(completion: dict[str, Any]) -> dict[str, Any]:
    return {
        "dj_profile": {
            "display_name": field_metric(completion, "dj_profile", "display_name"),
            "city_primary": field_metric(completion, "dj_profile", "city_primary"),
            "avatar_asset_id": field_metric(completion, "dj_profile", "avatar_asset_id"),
            "event_count_gt0": field_metric(completion, "dj_profile", "event_count_gt0"),
            "venue_count_gt0": field_metric(completion, "dj_profile", "venue_count_gt0"),
            "collaborator_count_gt0": field_metric(completion, "dj_profile", "collaborator_count_gt0"),
            "media_count_gt0": field_metric(completion, "dj_profile", "media_count_gt0"),
            "first_seen": field_metric(completion, "dj_profile", "first_seen"),
            "last_seen": field_metric(completion, "dj_profile", "last_seen"),
        },
        "performance_event": {
            "starts_at": field_metric(completion, "performance_event", "starts_at"),
            "time_text": field_metric(completion, "performance_event", "time_text"),
            "venue_name": field_metric(completion, "performance_event", "venue_name"),
            "city": field_metric(completion, "performance_event", "city"),
            "participant_count_gt0": field_metric(completion, "performance_event", "participant_count_gt0"),
        },
        "dj_event": {
            "starts_at": field_metric(completion, "dj_event", "starts_at"),
            "time_text": field_metric(completion, "dj_event", "time_text"),
            "venue_name": field_metric(completion, "dj_event", "venue_name"),
            "city": field_metric(completion, "dj_event", "city"),
            "source_ref": field_metric(completion, "dj_event", "source_ref"),
        },
        "dj_relation_rollup": {
            "same_event": field_metric(completion, "dj_relation_rollup", "same_event"),
            "same_venue": field_metric(completion, "dj_relation_rollup", "same_venue"),
            "same_source_context": field_metric(completion, "dj_relation_rollup", "same_source_context"),
            "sample_evidence": field_metric(completion, "dj_relation_rollup", "sample_evidence"),
        },
        "dj_venue_rollup": {
            "venue_name": field_metric(completion, "dj_venue_rollup", "venue_name"),
            "city": field_metric(completion, "dj_venue_rollup", "city"),
            "event_count_gt0": field_metric(completion, "dj_venue_rollup", "event_count_gt0"),
        },
    }


def overlay_snapshot(
    counts: dict[str, Any],
    attach_summary: dict[str, Any],
    ui_summary: dict[str, Any],
    ui_contract: dict[str, Any],
    validation_summary: dict[str, Any],
) -> dict[str, Any]:
    attach_counts = attach_summary.get("counts", attach_summary.get("overview_counts", {}))
    ui_counts = ui_summary.get("counts", {})
    validation_counts = validation_summary.get("counts", {})
    dj_total = int(counts.get("dj_profiles") or 0)
    overlay_entities = int(attach_counts.get("attach_ready_entity_rows") or ui_counts.get("attach_ready_entity_rows") or 0)
    overlay_links = int(attach_counts.get("overlay_link_rows") or ui_counts.get("overlay_link_rows") or 0)
    profile_rows = int(attach_counts.get("overlay_profile_rows") or ui_counts.get("overlay_profile_rows") or 0)
    outlink_rows = int(attach_counts.get("overlay_outlink_rows") or ui_counts.get("overlay_outlink_rows") or 0)
    return {
        "overlay_social_entities": overlay_entities,
        "overlay_social_entity_pct_of_all_djs": round(overlay_entities * 100.0 / dj_total, 2) if dj_total else 0.0,
        "overlay_link_rows": overlay_links,
        "overlay_profile_rows": profile_rows,
        "overlay_outlink_rows": outlink_rows,
        "overlay_avg_links_per_social_dj": round(overlay_links / overlay_entities, 2) if overlay_entities else 0.0,
        "serving_event_edges_for_social_entities": int(attach_counts.get("serving_event_edges_for_social_entities") or ui_counts.get("serving_event_edges_for_social_entities") or 0),
        "serving_relation_edges_for_social_entities": int(attach_counts.get("serving_relation_edges_for_social_entities") or ui_counts.get("serving_relation_edges_for_social_entities") or 0),
        "ui_cytoscape_elements": int(ui_counts.get("cytoscape_elements") or 0),
        "ui_cytoscape_nodes": int(ui_counts.get("cytoscape_nodes") or 0),
        "ui_cytoscape_edges": int(ui_counts.get("cytoscape_edges") or 0),
        "ui_routes": list(ui_contract.get("routes", [])),
        "ui_deployable_public": bool(ui_contract.get("public_state", {}).get("deployable_public", False)),
        "ui_requires_explicit_public_upload_gate": bool(ui_contract.get("public_state", {}).get("requires_explicit_public_upload_gate", False)),
        "manifest_merge_precheck_ready_rows": int(validation_counts.get("merge_precheck_ready_rows") or 0),
        "manifest_identity_review_required_rows": int(validation_counts.get("identity_review_required_rows") or 0),
        "manifest_avatar_hash_ready_rows": int(validation_counts.get("avatar_hash_ready_rows") or 0),
        "manifest_avatar_blocked_rows": int(validation_counts.get("avatar_blocked_rows") or 0),
    }


def doc_sync_snapshot(
    current_runtime: Path,
    documentation_index: Path,
    threads_index: Path,
    current_code_map: Path,
    stage7_overlay_ssot: Path,
) -> dict[str, Any]:
    runtime = read_text_head(current_runtime)
    doc_index = read_text_head(documentation_index)
    threads = read_text_head(threads_index)
    code_map = read_text_head(current_code_map)
    overlay_ssot = read_text_head(stage7_overlay_ssot)
    public_upload_recorded = "2026-05-27 00:10 Atlas Protected Graph UI Public Upload" in runtime
    overlay_ssot_public_upload_recorded = "2026-05-27 Atlas Protected Graph UI Public Upload" in overlay_ssot
    return {
        "current_runtime_records_protected_graph_ui_upload": public_upload_recorded,
        "stage7_overlay_ssot_records_protected_graph_ui_upload": overlay_ssot_public_upload_recorded,
        "documentation_index_has_0010_upload": "00:10" in doc_index,
        "threads_index_has_0010_upload": "00:10" in threads,
        "current_code_map_has_0010_upload": "00:10" in code_map,
        "ssot_drift_detected": bool(public_upload_recorded and not ("00:10" in doc_index and "00:10" in threads and "00:10" in code_map)),
        "public_surface_label": "atlas_public_graph_surface_guarded",
        "public_surface_path": "/atlas/graph",
        "upload_boundary": "guarded_static_ui_surface_only_not_data_write",
    }


def work_orders(counts: dict[str, Any], quality: dict[str, Any], overlay: dict[str, Any], doc_sync: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        {
            "lane": "T5_T6_social_overlay_persistence",
            "priority": 1,
            "status": "ready_for_schema_or_read_model_decision",
            "reason": "social overlay is validated locally but not persisted into source/raw or selected serving DB",
            "evidence": {
                "overlay_social_entities": overlay["overlay_social_entities"],
                "overlay_link_rows": overlay["overlay_link_rows"],
                "overlay_avg_links_per_social_dj": overlay["overlay_avg_links_per_social_dj"],
                "merge_precheck_ready_rows": overlay["manifest_merge_precheck_ready_rows"],
            },
            "next_action": "define new Atlas DB/social table migration or keep overlay as attach-only read model with explicit product decision",
        },
        {
            "lane": "T6_avatar_media_recovery",
            "priority": 2,
            "status": "blocked_needs_hash_readable_avatar_evidence",
            "reason": "all DJ avatar/media fields remain empty in the selected candidate",
            "evidence": {
                "dj_profile_avatar_missing": quality["dj_profile"]["avatar_asset_id"]["missing"],
                "dj_profile_media_missing": quality["dj_profile"]["media_count_gt0"]["missing"],
                "avatar_hash_ready_rows": overlay["manifest_avatar_hash_ready_rows"],
                "avatar_blocked_rows": overlay["manifest_avatar_blocked_rows"],
            },
            "next_action": "recover avatar artifacts as hash-addressed report-local files and rerun avatar validation before any public display",
        },
        {
            "lane": "T5_time_city_venue_gap",
            "priority": 3,
            "status": "large_gap_needs_source_context_or_OCR_recovery",
            "reason": "history/event surfaces are large, but exact time/city gaps remain material",
            "evidence": {
                "performance_event_starts_at_missing": quality["performance_event"]["starts_at"]["missing"],
                "performance_event_city_missing": quality["performance_event"]["city"]["missing"],
                "performance_event_venue_missing": quality["performance_event"]["venue_name"]["missing"],
                "dj_event_starts_at_missing": quality["dj_event"]["starts_at"]["missing"],
                "dj_event_city_missing": quality["dj_event"]["city"]["missing"],
                "dj_event_venue_missing": quality["dj_event"]["venue_name"]["missing"],
            },
            "next_action": "process source/OCR artifact recovery and deterministic time/venue queues before another serving rebuild",
        },
        {
            "lane": "T5_graph_ui_contract",
            "priority": 4,
            "status": "ready_for_rendered_local_smoke",
            "reason": "UI integration contract has graph/search/social routes and no dangling local contract edges",
            "evidence": {
                "ui_elements": overlay["ui_cytoscape_elements"],
                "ui_nodes": overlay["ui_cytoscape_nodes"],
                "ui_edges": overlay["ui_cytoscape_edges"],
                "routes": overlay["ui_routes"],
            },
            "next_action": "render local graph UI/API fixture smoke and verify filters/search/detail without additional public upload",
        },
    ]
    if doc_sync["ssot_drift_detected"]:
        rows.insert(
            0,
            {
                "lane": "T7_ssot_drift_reconciliation",
                "priority": 0,
                "status": "must_sync_before_next_takeover",
                "reason": "current-runtime and Stage7 overlay SSOT record a guarded public UI upload, while thread/index/code-map surfaces still point to 23:45 local-only state",
                "evidence": {
                    "current_runtime_records_upload": doc_sync["current_runtime_records_protected_graph_ui_upload"],
                    "documentation_index_has_0010_upload": doc_sync["documentation_index_has_0010_upload"],
                    "threads_index_has_0010_upload": doc_sync["threads_index_has_0010_upload"],
                    "current_code_map_has_0010_upload": doc_sync["current_code_map_has_0010_upload"],
                },
                "next_action": "sync T0/T5/T6/T7 and documentation indexes to the latest boundary without repeating remote upload",
            },
        )
    return rows


def leak_counts_for(payload: Any) -> dict[str, int]:
    counts = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}

    def visit(value: Any, key: str = "") -> None:
        if SECRET_KEY_RE.search(key):
            counts["sensitive_key_hits"] += 1
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(child_value, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str):
            counts["public_url_hits"] += len(URL_RE.findall(value))
            counts["sensitive_key_hits"] += len(SECRET_VALUE_RE.findall(value))
            counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(value))

    visit(payload)
    return counts


def report_md(summary: dict[str, Any], rollup: dict[str, Any], work_order_rows: list[dict[str, Any]]) -> str:
    counts = rollup["candidate_counts"]
    q = rollup["quality_snapshot"]
    overlay = rollup["sidecar_overlay_snapshot"]
    doc_sync = rollup["doc_sync_snapshot"]
    top_orders = "\n".join(
        f"- `{row['lane']}` priority `{row['priority']}`: {row['status']} — {row['reason']}"
        for row in work_order_rows[:6]
    )
    return f"""# Atlas T5/T6 DJ Completion Overlay Rollup

- generated_at: `{summary['generated_at']}`
- decision: `{summary['decision']}`
- failed_checks: `{summary['failed_checks']}`
- schema_version: `{summary['schema_version']}`

## LLM Audit Finding

The DJ-first Atlas candidate is no longer a generic graph-only artifact: it has a large historical performance/read-model surface plus a validated social/profile/outlink overlay. The main contradiction is SSOT drift: `current-runtime` and the Stage7 overlay SSOT record a guarded graph UI upload at `00:10`, while the thread/index/code-map surfaces still describe the `23:45` local-only UI integration smoke.

## Completion Effect

- DJ profiles: `{counts['dj_profiles']}` (`+{counts['delta_dj_profiles']}` vs base).
- Historical performance events: `{counts['performance_events']}` (`+{counts['delta_performance_events']}` vs base).
- DJ-event edges / directed DJ relations: `{counts['dj_event_edges']}` / `{counts['directed_relations']}` (`+{counts['delta_dj_event_edges']}` / `+{counts['delta_directed_relations']}`).
- Search docs / graph windows: `{counts['search_documents']}` / `{counts['graph_windows']}`.
- Mapped manual source/raw candidates already snapshotted upstream: `{counts['mapped_manual_candidate_rows']}`.

## Field Coverage

- DJ display/event coverage: display names `{q['dj_profile']['display_name']['pct']}%`, event_count `{q['dj_profile']['event_count_gt0']['pct']}%`, venue_count `{q['dj_profile']['venue_count_gt0']['pct']}%`, collaborator_count `{q['dj_profile']['collaborator_count_gt0']['pct']}%`.
- DJ city/avatar/media gaps: city missing `{q['dj_profile']['city_primary']['missing']}`, avatar missing `{q['dj_profile']['avatar_asset_id']['missing']}`, media missing `{q['dj_profile']['media_count_gt0']['missing']}`.
- Performance event time/venue/city: starts_at `{q['performance_event']['starts_at']['pct']}%`, time_text `{q['performance_event']['time_text']['pct']}%`, venue `{q['performance_event']['venue_name']['pct']}%`, city `{q['performance_event']['city']['pct']}%`.
- DJ-event edge time/venue/city: starts_at `{q['dj_event']['starts_at']['pct']}%`, venue `{q['dj_event']['venue_name']['pct']}%`, city `{q['dj_event']['city']['pct']}%`.
- Co-appearance relation evidence: same_event `{q['dj_relation_rollup']['same_event']['pct']}%`, same_venue `{q['dj_relation_rollup']['same_venue']['pct']}%`, sample_evidence `{q['dj_relation_rollup']['sample_evidence']['pct']}%`.

## Sidecar Overlay

- Social-enriched DJ entities: `{overlay['overlay_social_entities']}` / `{counts['dj_profiles']}` (`{overlay['overlay_social_entity_pct_of_all_djs']}%`).
- Social/profile/outlink rows: `{overlay['overlay_link_rows']}` / `{overlay['overlay_profile_rows']}` / `{overlay['overlay_outlink_rows']}`.
- Average social links per enriched DJ: `{overlay['overlay_avg_links_per_social_dj']}`.
- Social entities already join serving event/relation edges: `{overlay['serving_event_edges_for_social_entities']}` / `{overlay['serving_relation_edges_for_social_entities']}`.
- UI contract elements/nodes/edges: `{overlay['ui_cytoscape_elements']}` / `{overlay['ui_cytoscape_nodes']}` / `{overlay['ui_cytoscape_edges']}`.
- Identity/avatar follow-up still closed: identity review `{overlay['manifest_identity_review_required_rows']}`, avatar hash-ready/blocked `{overlay['manifest_avatar_hash_ready_rows']}` / `{overlay['manifest_avatar_blocked_rows']}`.

## SSOT Drift

- current-runtime upload recorded: `{doc_sync['current_runtime_records_protected_graph_ui_upload']}`
- Stage7 overlay SSOT upload recorded: `{doc_sync['stage7_overlay_ssot_records_protected_graph_ui_upload']}`
- Documentation index / thread index / code map synced to 00:10: `{doc_sync['documentation_index_has_0010_upload']}` / `{doc_sync['threads_index_has_0010_upload']}` / `{doc_sync['current_code_map_has_0010_upload']}`
- Drift detected: `{doc_sync['ssot_drift_detected']}`

## Next Work Orders

{top_orders}

## Safety

- leak_counts: public_url/sensitive_key/local_path `{summary['leak_counts']['public_url_hits']}/{summary['leak_counts']['sensitive_key_hits']}/{summary['leak_counts']['local_path_hits']}`.
- Boundary: report-only rollup from existing artifacts. No source/raw DB open, source/raw write, serving DB open/write/rebuild, graph/vector write, public pointer mutation, remote upload, mini-program upload/review, memory write, credential read, 9router, or D: root scan.
- next_resume_pointer: `{summary['next_resume_pointer']}`
"""


def build_packet(
    completion_summary_path: Path,
    overlay_attach_summary_path: Path,
    overlay_ui_summary_path: Path,
    overlay_ui_contract_path: Path,
    manifest_validation_summary_path: Path,
    current_runtime_path: Path,
    documentation_index_path: Path,
    threads_index_path: Path,
    current_code_map_path: Path,
    stage7_overlay_ssot_path: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    inputs = [
        completion_summary_path,
        overlay_attach_summary_path,
        overlay_ui_summary_path,
        overlay_ui_contract_path,
        manifest_validation_summary_path,
    ]
    failed: list[str] = []
    missing = [display_path(path) for path in inputs if not path.exists()]
    if missing:
        failed.append("required_input_missing")

    completion = read_json(completion_summary_path) if completion_summary_path.exists() else {}
    attach_summary = read_json(overlay_attach_summary_path) if overlay_attach_summary_path.exists() else {}
    ui_summary = read_json(overlay_ui_summary_path) if overlay_ui_summary_path.exists() else {}
    ui_contract = read_json(overlay_ui_contract_path) if overlay_ui_contract_path.exists() else {}
    validation_summary = read_json(manifest_validation_summary_path) if manifest_validation_summary_path.exists() else {}

    if completion.get("decision") != "atlas_dj_completion_effect_audit_ready_report_only":
        failed.append("completion_audit_not_ready")
    if attach_summary.get("decision") != "atlas_t6_sidecar_overlay_serving_attach_smoke_ready_report_only":
        failed.append("overlay_attach_not_ready")
    if ui_summary.get("decision") != "atlas_t6_sidecar_overlay_ui_integration_smoke_ready_report_only":
        failed.append("overlay_ui_integration_not_ready")
    if validation_summary.get("decision") != "atlas_t6_sidecar_manifest_validation_gate_ready_report_only":
        failed.append("sidecar_manifest_validation_not_ready")
    if ui_contract.get("report_only") is not True:
        failed.append("overlay_ui_contract_not_report_only")
    if any(completion.get("write_guards", {}).get(key) not in (False, None) for key in WRITE_GUARD_KEYS):
        failed.append("upstream_completion_write_guard_open")

    counts = summary_counts(completion)
    quality = build_quality_snapshot(completion)
    overlay = overlay_snapshot(counts, attach_summary, ui_summary, ui_contract, validation_summary)
    doc_sync = doc_sync_snapshot(current_runtime_path, documentation_index_path, threads_index_path, current_code_map_path, stage7_overlay_ssot_path)
    work_order_rows = work_orders(counts, quality, overlay, doc_sync)

    rollup = {
        "schema_version": f"{SCHEMA_VERSION}.rollup",
        "generated_at": now_iso(),
        "report_only": True,
        "candidate_counts": counts,
        "quality_snapshot": quality,
        "sidecar_overlay_snapshot": overlay,
        "doc_sync_snapshot": doc_sync,
        "work_order_count": len(work_order_rows),
        "input_artifacts": {
            "completion_summary": artifact_ref(completion_summary_path),
            "overlay_attach_summary": artifact_ref(overlay_attach_summary_path),
            "overlay_ui_summary": artifact_ref(overlay_ui_summary_path),
            "overlay_ui_contract": artifact_ref(overlay_ui_contract_path),
            "manifest_validation_summary": artifact_ref(manifest_validation_summary_path),
        },
        "write_guards": {
            "source_raw_db_opened": False,
            "source_raw_db_write_executed": False,
            "serving_sqlite_opened": False,
            "serving_sqlite_write_executed": False,
            "serving_rebuild_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_sqlite_write_executed": False,
            "public_pointer_updated": False,
            "remote_upload_executed": False,
            "mini_program_upload_review_executed": False,
            "memory_write_executed": False,
        },
    }

    leak_counts = leak_counts_for(rollup)
    if any(leak_counts.values()):
        failed.append("rollup_payload_leak_scan_hits")
    if counts["dj_profiles"] <= 0 or counts["performance_events"] <= 0 or counts["dj_event_edges"] <= 0:
        failed.append("candidate_core_counts_not_positive")
    if overlay["overlay_social_entities"] <= 0 or overlay["overlay_link_rows"] <= 0:
        failed.append("overlay_social_counts_not_positive")

    decision = "atlas_dj_completion_overlay_rollup_ready_report_only" if not failed else "atlas_dj_completion_overlay_rollup_blocked_report_only"
    summary = {
        "schema_version": f"{SCHEMA_VERSION}.summary",
        "generated_at": rollup["generated_at"],
        "decision": decision,
        "failed_checks": failed,
        "counts": {
            **counts,
            "overlay_social_entities": overlay["overlay_social_entities"],
            "overlay_link_rows": overlay["overlay_link_rows"],
            "overlay_profile_rows": overlay["overlay_profile_rows"],
            "overlay_outlink_rows": overlay["overlay_outlink_rows"],
            "work_order_rows": len(work_order_rows),
            "ssot_drift_detected_rows": 1 if doc_sync["ssot_drift_detected"] else 0,
        },
        "quality_gap_counts": {
            "dj_profile_city_missing": quality["dj_profile"]["city_primary"]["missing"],
            "dj_profile_avatar_missing": quality["dj_profile"]["avatar_asset_id"]["missing"],
            "dj_profile_media_missing": quality["dj_profile"]["media_count_gt0"]["missing"],
            "performance_event_starts_at_missing": quality["performance_event"]["starts_at"]["missing"],
            "performance_event_city_missing": quality["performance_event"]["city"]["missing"],
            "performance_event_venue_missing": quality["performance_event"]["venue_name"]["missing"],
            "dj_event_starts_at_missing": quality["dj_event"]["starts_at"]["missing"],
            "dj_event_city_missing": quality["dj_event"]["city"]["missing"],
            "dj_event_venue_missing": quality["dj_event"]["venue_name"]["missing"],
        },
        "sidecar_overlay": overlay,
        "doc_sync": doc_sync,
        "leak_counts": leak_counts,
        "write_guards": rollup["write_guards"],
        "outputs": {
            "rollup_json": display_path(out_dir / "dj_completion_overlay_rollup.json"),
            "work_orders": display_path(out_dir / "dj_completion_next_work_orders.jsonl"),
            "summary_json": display_path(out_dir / "dj_completion_overlay_rollup_summary.json"),
            "summary_md": display_path(out_dir / "dj_completion_overlay_rollup_summary.md"),
            "report": display_path(report_path),
        },
        "next_resume_pointer": display_path(out_dir / "dj_completion_next_work_orders.jsonl"),
        "stop_reason": "dj_completion_overlay_rollup_ready_for_ssot_sync_and_next_work_orders" if not failed else "dj_completion_overlay_rollup_blocked",
        "wait_reason": "Sync SSOT drift, then execute top work order without repeating public upload." if not failed else "Fix failed checks before downstream work.",
    }

    write_json(out_dir / "dj_completion_overlay_rollup.json", rollup)
    write_jsonl(out_dir / "dj_completion_next_work_orders.jsonl", work_order_rows)
    write_json(out_dir / "dj_completion_overlay_rollup_summary.json", summary)
    write_text(out_dir / "dj_completion_overlay_rollup_summary.md", report_md(summary, rollup, work_order_rows))
    write_text(report_path, report_md(summary, rollup, work_order_rows))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--completion-summary", type=Path, default=DEFAULT_COMPLETION_SUMMARY)
    parser.add_argument("--overlay-attach-summary", type=Path, default=DEFAULT_OVERLAY_ATTACH_SUMMARY)
    parser.add_argument("--overlay-ui-summary", type=Path, default=DEFAULT_OVERLAY_UI_SUMMARY)
    parser.add_argument("--overlay-ui-contract", type=Path, default=DEFAULT_OVERLAY_UI_CONTRACT)
    parser.add_argument("--manifest-validation-summary", type=Path, default=DEFAULT_MANIFEST_VALIDATION_SUMMARY)
    parser.add_argument("--current-runtime", type=Path, default=DEFAULT_CURRENT_RUNTIME)
    parser.add_argument("--documentation-index", type=Path, default=DEFAULT_DOCUMENTATION_INDEX)
    parser.add_argument("--threads-index", type=Path, default=DEFAULT_THREADS_INDEX)
    parser.add_argument("--current-code-map", type=Path, default=DEFAULT_CURRENT_CODE_MAP)
    parser.add_argument("--stage7-overlay-ssot", type=Path, default=DEFAULT_STAGE7_OVERLAY_SSOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    summary = build_packet(
        args.completion_summary,
        args.overlay_attach_summary,
        args.overlay_ui_summary,
        args.overlay_ui_contract,
        args.manifest_validation_summary,
        args.current_runtime,
        args.documentation_index,
        args.threads_index,
        args.current_code_map,
        args.stage7_overlay_ssot,
        args.out_dir,
        args.report,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
