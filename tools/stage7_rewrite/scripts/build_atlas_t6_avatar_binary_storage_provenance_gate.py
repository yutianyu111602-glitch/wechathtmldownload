#!/usr/bin/env python3
"""Build a report-only binary/storage provenance gate for Atlas avatar display.

This gate consumes the DJ-first avatar entity binding output. It resolves
duplicate primary-avatar candidates deterministically, checks optional explicit
binary/source and storage target roots, and emits prewrite/rollback/postwrite
contracts. It never downloads avatars or writes storage.
"""
from __future__ import annotations

import argparse
import hashlib
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import build_atlas_t6_avatar_media_recovery_packet as recovery


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_BINDING_DIR = STAGE7_ROOT / "reports" / "atlas_t6_avatar_entity_binding_gate_20260527"
DEFAULT_MANIFEST_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_redacted_manifest_20260526_v4"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_avatar_binary_storage_provenance_gate_20260527"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_AVATAR_BINARY_STORAGE_PROVENANCE_GATE_20260527.md"
SCHEMA_VERSION = "stage7_atlas_t6_avatar_binary_storage_provenance_gate.v1"

BASE_WRITE_GUARDS = {
    "report_only": True,
    "write_execution_allowed_now": False,
    "source_raw_db_opened": False,
    "source_raw_db_write_executed": False,
    "serving_sqlite_opened": False,
    "serving_sqlite_write_or_rebuild_executed": False,
    "storage_write_executed": False,
    "network_fetch_executed": False,
    "model_call_executed": False,
    "ocr_executed": False,
    "neo4j_write_executed": False,
    "qdrant_write_executed": False,
    "production_sqlite_write_executed": False,
    "public_pointer_updated": False,
    "huaidj_club_upload_executed": False,
    "mini_program_upload_or_review_executed": False,
    "memory_write_executed": False,
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def safe_root_status(path: Path | None, label: str) -> dict[str, Any]:
    if path is None:
        return {
            f"{label}_provided": False,
            f"{label}_exists": False,
            f"{label}_hash": "",
            f"{label}_basename": "",
        }
    recovery.reject_unbounded_d_root(path, label)
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    return {
        f"{label}_provided": True,
        f"{label}_exists": path.exists(),
        f"{label}_hash": recovery.stable_hash(str(resolved), 24),
        f"{label}_basename": resolved.name,
    }


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            total += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), total


def index_binary_source_root(root: Path | None, max_files: int) -> tuple[dict[tuple[str, int], dict[str, Any]], dict[str, Any]]:
    if root is None or not root.exists():
        return {}, {"files_scanned": 0, "hash_rows": 0, "scan_blocked": False, "binary_file_opened": False}
    recovery.reject_unbounded_d_root(root, "binary_source_root")
    if not root.is_dir():
        file_hash, file_size = sha256_file(root)
        return {
            (file_hash, file_size): {
                "binary_source_file_hash": recovery.stable_hash(str(root.resolve()), 24),
                "binary_source_file_basename": root.name,
                "local_file_sha256": file_hash,
                "file_size_bytes": file_size,
            }
        }, {"files_scanned": 1, "hash_rows": 1, "scan_blocked": False, "binary_file_opened": True}

    index: dict[tuple[str, int], dict[str, Any]] = {}
    files_scanned = 0
    scan_blocked = False
    for child in root.rglob("*"):
        if not child.is_file():
            continue
        files_scanned += 1
        if files_scanned > max_files:
            scan_blocked = True
            break
        file_hash, file_size = sha256_file(child)
        index[(file_hash, file_size)] = {
            "binary_source_file_hash": recovery.stable_hash(str(child.resolve()), 24),
            "binary_source_file_basename": child.name,
            "local_file_sha256": file_hash,
            "file_size_bytes": file_size,
        }
    return index, {
        "files_scanned": files_scanned,
        "hash_rows": len(index),
        "scan_blocked": scan_blocked,
        "binary_file_opened": files_scanned > 0,
    }


def choose_primary(rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str]:
    if not rows:
        return None, [], "no_candidate"
    sortable = []
    unresolved = []
    for row in rows:
        local_hash = str(row.get("local_file_sha256") or "")
        file_size = int(row.get("file_size_bytes") or 0)
        if not recovery.HASH64_RE.match(local_hash) or file_size <= 0:
            unresolved.append(row)
        sortable.append((-file_size, local_hash, str(row.get("avatar_id_hash") or ""), row))
    if unresolved:
        return None, rows, "hash_or_size_missing_review_required"
    sortable.sort(key=lambda item: item[:3])
    selected = sortable[0][3]
    superseded = [item[3] for item in sortable[1:]]
    if len(rows) == 1:
        return selected, superseded, "single_avatar_primary_candidate_report_only"
    return selected, superseded, "deterministic_largest_file_primary_candidate_report_only"


def build_primary_rows(bound_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    by_dj: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in bound_rows:
        by_dj[str(row.get("serving_dj_id") or "")].append(row)

    primary_rows: list[dict[str, Any]] = []
    superseded_rows: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, Any]] = []
    for dj_id, rows in sorted(by_dj.items()):
        selected, superseded, status = choose_primary(rows)
        group_hash = recovery.stable_hash({"dj_id": dj_id, "avatars": sorted(str(row.get("avatar_id_hash") or "") for row in rows)}, 24)
        if selected is None:
            for row in unresolved_rows_for_group(rows, group_hash, status):
                unresolved_rows.append(row)
            continue
        primary = {
            "accepted_for_graph": False,
            "avatar_id_hash": selected.get("avatar_id_hash"),
            "binding_selector_hash": selected.get("binding_selector_hash"),
            "content_addressed_storage_key_hash": selected.get("content_addressed_storage_key_hash"),
            "content_addressed_storage_key_preview": selected.get("content_addressed_storage_key_preview"),
            "entity_name": selected.get("entity_name"),
            "file_size_bytes": int(selected.get("file_size_bytes") or 0),
            "graph_write_allowed": False,
            "local_file_sha256": selected.get("local_file_sha256") or "",
            "memory_write_allowed": False,
            "platform": selected.get("platform") or "unknown",
            "primary_avatar_selection_status": status,
            "primary_selector_group_hash": group_hash,
            "public_serving_field_allowed": False,
            "serving_display_name": selected.get("serving_display_name"),
            "serving_dj_id": selected.get("serving_dj_id"),
            "serving_rebuild_allowed": False,
            "source_raw_db_write_allowed": False,
            "storage_write_allowed_now": False,
            "superseded_avatar_count": len(superseded),
            "write_execution_allowed_now": False,
        }
        primary_rows.append(primary)
        for row in superseded:
            superseded_rows.append(
                {
                    "accepted_for_graph": False,
                    "avatar_id_hash": row.get("avatar_id_hash"),
                    "binding_selector_hash": row.get("binding_selector_hash"),
                    "blockers": ["superseded_by_deterministic_primary_avatar_candidate"],
                    "entity_name": row.get("entity_name"),
                    "file_size_bytes": int(row.get("file_size_bytes") or 0),
                    "graph_write_allowed": False,
                    "local_file_sha256": row.get("local_file_sha256") or "",
                    "memory_write_allowed": False,
                    "platform": row.get("platform") or "unknown",
                    "primary_selector_group_hash": group_hash,
                    "public_serving_field_allowed": False,
                    "selected_primary_avatar_id_hash": selected.get("avatar_id_hash"),
                    "serving_dj_id": row.get("serving_dj_id"),
                    "serving_rebuild_allowed": False,
                    "source_raw_db_write_allowed": False,
                    "storage_write_allowed_now": False,
                    "write_execution_allowed_now": False,
                }
            )
    return primary_rows, superseded_rows, unresolved_rows


def unresolved_rows_for_group(rows: list[dict[str, Any]], group_hash: str, status: str) -> Iterable[dict[str, Any]]:
    for row in rows:
        yield {
            "accepted_for_graph": False,
            "avatar_id_hash": row.get("avatar_id_hash"),
            "binding_selector_hash": row.get("binding_selector_hash"),
            "blockers": [status],
            "entity_name": row.get("entity_name"),
            "file_size_bytes": int(row.get("file_size_bytes") or 0),
            "graph_write_allowed": False,
            "local_file_sha256": row.get("local_file_sha256") or "",
            "memory_write_allowed": False,
            "platform": row.get("platform") or "unknown",
            "primary_selector_group_hash": group_hash,
            "public_serving_field_allowed": False,
            "serving_dj_id": row.get("serving_dj_id"),
            "serving_rebuild_allowed": False,
            "source_raw_db_write_allowed": False,
            "storage_write_allowed_now": False,
            "write_execution_allowed_now": False,
        }


def storage_object_key(local_file_sha256: str) -> str:
    return f"atlas-avatar-sha256/{local_file_sha256[:2]}/{local_file_sha256}"


def build_storage_rows(
    primary_rows: list[dict[str, Any]],
    binary_index: dict[tuple[str, int], dict[str, Any]],
    binary_source_ready: bool,
    storage_target_ready: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ready_rows: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []
    for row in primary_rows:
        local_hash = str(row.get("local_file_sha256") or "")
        file_size = int(row.get("file_size_bytes") or 0)
        binary_match = binary_index.get((local_hash, file_size))
        blockers: list[str] = []
        if not binary_source_ready:
            blockers.append("explicit_binary_source_root_missing")
        elif binary_match is None:
            blockers.append("binary_source_checksum_readback_missing")
        if not storage_target_ready:
            blockers.append("explicit_storage_target_root_missing")
        object_key = storage_object_key(local_hash) if recovery.HASH64_RE.match(local_hash) else ""
        base = {
            "accepted_for_graph": False,
            "avatar_id_hash": row.get("avatar_id_hash"),
            "binary_source_file_basename": binary_match.get("binary_source_file_basename", "") if binary_match else "",
            "binary_source_file_hash": binary_match.get("binary_source_file_hash", "") if binary_match else "",
            "binary_source_provenance_ready": bool(binary_match),
            "checksum_readback_required": True,
            "file_size_bytes": file_size,
            "graph_write_allowed": False,
            "local_file_sha256": local_hash,
            "memory_write_allowed": False,
            "object_key_hash": recovery.stable_hash(object_key, 24) if object_key else "",
            "object_key_preview": f"atlas-avatar-sha256/{local_hash[:2]}/{local_hash[:12]}..." if object_key else "",
            "platform": row.get("platform") or "unknown",
            "postwrite_readback_selector_hash": recovery.stable_hash(f"postwrite|{row.get('serving_dj_id')}|{local_hash}|{file_size}", 24),
            "primary_avatar_selection_status": row.get("primary_avatar_selection_status"),
            "public_serving_field_allowed": False,
            "rollback_selector_hash": recovery.stable_hash(f"rollback|{row.get('serving_dj_id')}|{row.get('avatar_id_hash')}|{local_hash}", 24),
            "serving_dj_id": row.get("serving_dj_id"),
            "serving_display_name": row.get("serving_display_name"),
            "serving_rebuild_allowed": False,
            "source_raw_db_write_allowed": False,
            "storage_target_provenance_ready": storage_target_ready,
            "storage_write_allowed_now": False,
            "write_execution_allowed_now": False,
        }
        if blockers:
            blocked = dict(base)
            blocked["avatar_binary_storage_status"] = "binary_storage_provenance_blocked_report_only"
            blocked["blockers"] = blockers
            blocked_rows.append(blocked)
            continue
        ready = dict(base)
        ready["avatar_binary_storage_status"] = "binary_storage_provenance_ready_report_only"
        ready["blockers"] = ["storage_write_gate_required", "serving_rebuild_gate_required", "public_display_gate_closed"]
        ready_rows.append(ready)
    return ready_rows, blocked_rows


def build_binding_repair_rows(binding_blocked_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    repair_rows: list[dict[str, Any]] = []
    for row in binding_blocked_rows:
        repair_rows.append(
            {
                "accepted_for_graph": False,
                "avatar_id_hash": row.get("avatar_id_hash"),
                "blockers": row.get("blockers", []),
                "candidate_serving_dj_ids": row.get("candidate_serving_dj_ids", []),
                "entity_kind": row.get("entity_kind"),
                "entity_name": row.get("entity_name"),
                "entity_name_hash": row.get("entity_name_hash"),
                "graph_write_allowed": False,
                "memory_write_allowed": False,
                "next_gate": "manual_alias_or_source_context_binding_repair_before_avatar_display",
                "platform": row.get("platform") or "unknown",
                "public_serving_field_allowed": False,
                "repair_status": "serving_dj_id_binding_repair_required_report_only",
                "serving_rebuild_allowed": False,
                "source_raw_db_write_allowed": False,
                "storage_write_allowed_now": False,
                "write_execution_allowed_now": False,
            }
        )
    return repair_rows


def write_report(path: Path, summary: dict[str, Any]) -> None:
    counts = summary["counts"]
    lines = [
        "# Atlas T6 Avatar Binary Storage Provenance Gate 20260527",
        "",
        f"Generated: `{summary['generated_at']}`",
        "",
        "## Decision",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Bound input / primary candidates / storage-ready rows: `{counts['input_bound_rows']}/{counts['primary_avatar_candidate_rows']}/{counts['binary_storage_ready_rows']}`",
        f"- Storage blocked / binding repair rows: `{counts['binary_storage_blocked_rows']}/{counts['binding_repair_work_order_rows']}`",
        f"- Duplicate groups resolved / unresolved: `{counts['duplicate_primary_groups_resolved']}/{counts['primary_selection_unresolved_rows']}`",
        f"- Binary source / storage target provenance-ready rows: `{counts['binary_source_provenance_ready_rows']}/{counts['storage_target_provenance_ready_rows']}`",
        f"- Leak hits public URL / sensitive key / local path: `{summary['leak_scan']['public_url_hits']}/{summary['leak_scan']['sensitive_key_hits']}/{summary['leak_scan']['local_path_hits']}`",
        "",
        "## LLM Audit Finding",
        "",
        "- The duplicate `DJ OXY` primary-avatar review is deterministically resolvable by the largest-byte-size rule, leaving no primary-selection review rows in this gate.",
        "- The real blocker is now narrower: no explicit binary source root and no explicit storage target root are bound to the avatar display lane, so storage/public fields remain closed.",
        "- `DJ HEARTSTRING` remains a separate serving-identity binding repair work order, not a storage problem.",
        "",
        "## Boundary Truth",
        "",
        "- Report-only provenance/write contract. No network fetch, avatar download, storage write, source/raw DB mutation, serving rebuild/write, graph/vector/public mutation, huaidj.club upload, mini-program upload/review, memory write, model/OCR call, 9router, destructive Git, or D: root scan occurred.",
        "- Binary files are opened only when an explicit bounded `--binary-source-root` is provided; the default run opens none.",
        "",
        "## Evidence",
        "",
        f"- Summary: `{summary['outputs']['summary_json']}`",
        f"- Contract: `{summary['outputs']['contract_json']}`",
        f"- Primary candidates: `{summary['outputs']['primary_avatar_candidates']}`",
        f"- Binary/storage ready rows: `{summary['outputs']['binary_storage_ready_rows']}`",
        f"- Binary/storage blocked rows: `{summary['outputs']['binary_storage_blocked_rows']}`",
        f"- Binding repair work orders: `{summary['outputs']['binding_repair_work_orders']}`",
        "",
        "## Next Resume Pointer",
        "",
        f"`{summary['next_resume_pointer']}`",
        "",
    ]
    recovery.write_text(path, "\n".join(lines))


def build(args: argparse.Namespace) -> dict[str, Any]:
    binding_dir = Path(args.binding_dir)
    manifest_dir = Path(args.manifest_dir)
    out_dir = Path(args.out_dir)
    report_path = Path(args.report)
    binary_source_root = Path(args.binary_source_root) if args.binary_source_root else None
    storage_target_root = Path(args.storage_target_root) if args.storage_target_root else None

    bound_rows = recovery.read_jsonl(binding_dir / "avatar_entity_binding_ready_report_only.jsonl", "avatar binding ready rows")
    binding_blocked_rows = recovery.read_jsonl(binding_dir / "avatar_entity_binding_blocked_rows.jsonl", "avatar binding blocked rows")
    primary_review_rows = recovery.read_jsonl(binding_dir / "avatar_primary_selection_review_rows.jsonl", "avatar primary review rows")
    binding_summary = recovery.read_json(binding_dir / "avatar_entity_binding_summary.json", "avatar binding summary")
    manifest = recovery.read_json(manifest_dir / "manifest.json", "v4 manifest")
    provenance_summary = recovery.read_json(manifest_dir / "provenance_summary.json", "v4 provenance summary")

    binary_root_status = safe_root_status(binary_source_root, "binary_source_root")
    storage_root_status = safe_root_status(storage_target_root, "storage_target_root")
    binary_source_ready = bool(binary_root_status["binary_source_root_exists"])
    storage_target_ready = bool(storage_root_status["storage_target_root_exists"])
    binary_index, binary_scan = index_binary_source_root(binary_source_root, int(args.max_binary_files))

    primary_rows, superseded_rows, primary_unresolved_rows = build_primary_rows(bound_rows)
    storage_ready_rows, storage_blocked_rows = build_storage_rows(
        primary_rows,
        binary_index,
        binary_source_ready,
        storage_target_ready,
    )
    binding_repair_rows = build_binding_repair_rows(binding_blocked_rows)

    primary_path = out_dir / "avatar_primary_selection_candidates.jsonl"
    superseded_path = out_dir / "avatar_primary_selection_superseded_rows.jsonl"
    unresolved_path = out_dir / "avatar_primary_selection_unresolved_rows.jsonl"
    ready_path = out_dir / "avatar_binary_storage_ready_report_only.jsonl"
    blocked_path = out_dir / "avatar_binary_storage_blocked_rows.jsonl"
    repair_path = out_dir / "avatar_binding_repair_work_orders.jsonl"
    contract_path = out_dir / "avatar_binary_storage_provenance_contract.json"
    summary_path = out_dir / "avatar_binary_storage_provenance_summary.json"
    leak_path = out_dir / "leak_scan.json"
    summary_md_path = out_dir / "avatar_binary_storage_provenance_summary.md"

    duplicate_group_counts = Counter(str(row.get("serving_dj_id") or "") for row in bound_rows)
    duplicate_group_total = sum(1 for _, count in duplicate_group_counts.items() if count > 1)
    duplicate_groups_resolved = sum(1 for row in primary_rows if int(row.get("superseded_avatar_count") or 0) > 0)
    counts = {
        "input_bound_rows": len(bound_rows),
        "input_primary_review_rows": len(primary_review_rows),
        "input_binding_blocked_rows": len(binding_blocked_rows),
        "primary_avatar_candidate_rows": len(primary_rows),
        "primary_avatar_superseded_rows": len(superseded_rows),
        "primary_selection_unresolved_rows": len(primary_unresolved_rows),
        "duplicate_primary_groups_input": duplicate_group_total,
        "duplicate_primary_groups_resolved": duplicate_groups_resolved,
        "binary_storage_ready_rows": len(storage_ready_rows),
        "binary_storage_blocked_rows": len(storage_blocked_rows),
        "binding_repair_work_order_rows": len(binding_repair_rows),
        "binary_source_provenance_ready_rows": sum(1 for row in storage_ready_rows if row.get("binary_source_provenance_ready")),
        "storage_target_provenance_ready_rows": sum(1 for row in storage_ready_rows if row.get("storage_target_provenance_ready")),
        "source_raw_db_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "storage_write_allowed_now_rows": 0,
        "memory_write_allowed_rows": 0,
        "binary_source_files_scanned": int(binary_scan["files_scanned"]),
        "binary_source_hash_rows": int(binary_scan["hash_rows"]),
    }

    write_guards = dict(BASE_WRITE_GUARDS)
    write_guards["binary_file_opened"] = bool(binary_scan["binary_file_opened"])
    contract = {
        "schema_version": f"{SCHEMA_VERSION}.contract",
        "generated_at": now_iso(),
        "decision": "atlas_t6_avatar_binary_storage_provenance_gate_blocked_report_only",
        "report_only": True,
        "source_binding_decision": binding_summary.get("decision"),
        "source_manifest_run_id": manifest.get("run_id"),
        "source_manifest_avatar_artifact_count": manifest.get("avatar_artifact_count"),
        "source_provenance": {
            "runtime_mode": (provenance_summary.get("runtime") or {}).get("snapshot_mode"),
            "raw_url_emitted": False,
            "local_path_emitted": False,
            "swarm_db_basename": ((provenance_summary.get("source_inputs") or {}).get("swarm_db") or {}).get("basename", ""),
            "atlas_db_basename": ((provenance_summary.get("source_inputs") or {}).get("atlas_db") or {}).get("basename", ""),
        },
        "binary_source_root": binary_root_status,
        "storage_target_root": storage_root_status,
        "binary_scan": binary_scan,
        "primary_selection_policy": {
            "duplicate_rule": "choose largest file_size_bytes, then local_file_sha256, then avatar_id_hash",
            "manual_review_required_when_hash_or_size_missing": True,
            "raw_urls_emitted": False,
            "local_paths_emitted": False,
        },
        "prewrite_requirements": [
            "provide an explicit bounded binary source root or artifact bundle and verify sha256 plus byte-size readback",
            "provide an explicit storage target root or object-store namespace and record target hash, not raw path, in report outputs",
            "write only primary-avatar candidates; superseded duplicate candidates remain rollback/reference evidence",
            "materialize derived serving candidate instead of mutating selected serving SQLite in place",
        ],
        "rollback_requirements": [
            "delete or detach only storage objects named by object_key_hash/object_key_preview after checksum readback",
            "restore dj_profile avatar/media fields from prewrite snapshots before any public-serving approval",
            "keep superseded avatar rows as evidence-only rows, not product display rows",
        ],
        "postwrite_requirements": [
            "read back storage object sha256 and byte size for every primary candidate",
            "read back derived serving detail/search/graph responses for every target dj_id",
            "run local avatar UI/API smoke before any public-serving field approval",
        ],
        "write_guards": write_guards,
    }

    leak_payload = {
        "contract": contract,
        "primary_rows": primary_rows,
        "superseded_rows": superseded_rows,
        "primary_unresolved_rows": primary_unresolved_rows,
        "storage_ready_rows": storage_ready_rows,
        "storage_blocked_rows": storage_blocked_rows,
        "binding_repair_rows": binding_repair_rows,
    }
    leak_scan = recovery.leak_counts_for(leak_payload)
    failed_checks: list[str] = []
    if primary_unresolved_rows:
        failed_checks.append("primary_avatar_selection_unresolved_rows_present")
    if binding_repair_rows:
        failed_checks.append("binding_repair_rows_present")
    if not binary_source_ready:
        failed_checks.append("binary_source_provenance_missing")
    if binary_scan.get("scan_blocked"):
        failed_checks.append("binary_source_scan_limit_reached")
    if binary_source_ready and any("binary_source_checksum_readback_missing" in row.get("blockers", []) for row in storage_blocked_rows):
        failed_checks.append("binary_source_checksum_readback_missing")
    if not storage_target_ready:
        failed_checks.append("storage_target_provenance_missing")
    if any(leak_scan.values()):
        failed_checks.append("leak_scan_hits_present")

    decision = "atlas_t6_avatar_binary_storage_provenance_gate_ready_report_only" if not failed_checks and storage_ready_rows else "atlas_t6_avatar_binary_storage_provenance_gate_blocked_report_only"
    contract["decision"] = decision
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": contract["generated_at"],
        "decision": decision,
        "failed_checks": failed_checks,
        "counts": counts,
        "blocker_counts_top": recovery.top_counts(Counter(blocker for row in storage_blocked_rows + binding_repair_rows for blocker in row.get("blockers", []))),
        "platform_counts_top": recovery.top_counts(Counter(str(row.get("platform") or "unknown") for row in primary_rows)),
        "leak_scan": leak_scan,
        "write_guards": write_guards,
        "inputs": {
            "binding_summary": recovery.display_path(binding_dir / "avatar_entity_binding_summary.json"),
            "binding_ready_rows": recovery.display_path(binding_dir / "avatar_entity_binding_ready_report_only.jsonl"),
            "binding_blocked_rows": recovery.display_path(binding_dir / "avatar_entity_binding_blocked_rows.jsonl"),
            "primary_selection_review_rows": recovery.display_path(binding_dir / "avatar_primary_selection_review_rows.jsonl"),
            "v4_manifest": recovery.display_path(manifest_dir / "manifest.json"),
            "v4_provenance_summary": recovery.display_path(manifest_dir / "provenance_summary.json"),
        },
        "outputs": {
            "summary_json": recovery.display_path(summary_path),
            "contract_json": recovery.display_path(contract_path),
            "primary_avatar_candidates": recovery.display_path(primary_path),
            "primary_avatar_superseded_rows": recovery.display_path(superseded_path),
            "primary_avatar_unresolved_rows": recovery.display_path(unresolved_path),
            "binary_storage_ready_rows": recovery.display_path(ready_path),
            "binary_storage_blocked_rows": recovery.display_path(blocked_path),
            "binding_repair_work_orders": recovery.display_path(repair_path),
            "summary_md": recovery.display_path(summary_md_path),
            "report": recovery.display_path(report_path),
        },
        "boundary_truth": {
            "binary_file_opened": bool(binary_scan["binary_file_opened"]),
            "storage_write_executed": False,
            "source_raw_db_opened": False,
            "source_raw_db_write_executed": False,
            "serving_sqlite_opened": False,
            "serving_sqlite_write_or_rebuild_executed": False,
            "graph_vector_public_mutation_executed": False,
            "huaidj_club_upload_executed": False,
        },
        "next_resume_pointer": recovery.display_path(blocked_path if storage_blocked_rows else ready_path),
    }

    recovery.write_json(contract_path, contract)
    recovery.write_jsonl(primary_path, primary_rows)
    recovery.write_jsonl(superseded_path, superseded_rows)
    recovery.write_jsonl(unresolved_path, primary_unresolved_rows)
    recovery.write_jsonl(ready_path, storage_ready_rows)
    recovery.write_jsonl(blocked_path, storage_blocked_rows)
    recovery.write_jsonl(repair_path, binding_repair_rows)
    recovery.write_json(leak_path, leak_scan)
    recovery.write_json(summary_path, summary)
    recovery.write_text(summary_md_path, f"# Avatar Binary Storage Provenance Summary\n\nDecision: `{decision}`\n\nNext: `{summary['next_resume_pointer']}`\n")
    write_report(report_path, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding-dir", default=str(DEFAULT_BINDING_DIR))
    parser.add_argument("--manifest-dir", default=str(DEFAULT_MANIFEST_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--binary-source-root", default="")
    parser.add_argument("--storage-target-root", default="")
    parser.add_argument("--max-binary-files", type=int, default=5000)
    return parser.parse_args()


def json_summary(summary: dict[str, Any]) -> str:
    import json

    return json.dumps(
        {
            "decision": summary["decision"],
            "failed_checks": summary["failed_checks"],
            "counts": summary["counts"],
            "next_resume_pointer": summary["next_resume_pointer"],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def main() -> None:
    print(json_summary(build(parse_args())))


if __name__ == "__main__":
    main()
