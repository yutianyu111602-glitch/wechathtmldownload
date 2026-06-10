#!/usr/bin/env python3
"""Build a report-only DJ avatar entity-binding gate for Atlas T6 evidence.

This gate consumes the avatar storage contract, the v4 sidecar redacted
manifest, and the selected Atlas serving SQLite in read-only mode. It binds
DJ-first avatar candidates to serving `dj_profile.dj_id` when deterministic,
records duplicate primary-avatar review requirements, and keeps storage,
serving, graph, vector, public, and memory writes closed until an explicit
binary/storage target and postwrite readback gate exists.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import build_atlas_t6_avatar_media_recovery_packet as recovery


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_STORAGE_DIR = STAGE7_ROOT / "reports" / "atlas_t6_avatar_storage_contract_gate_20260527"
DEFAULT_MANIFEST_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_redacted_manifest_20260526_v4"
DEFAULT_SERVING_DB = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "atlas_serving.sqlite"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_avatar_entity_binding_gate_20260527"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_AVATAR_ENTITY_BINDING_GATE_20260527.md"
SCHEMA_VERSION = "stage7_atlas_t6_avatar_entity_binding_gate.v1"

WRITE_GUARDS = {
    "report_only": True,
    "write_execution_allowed_now": False,
    "source_raw_db_opened": False,
    "source_raw_db_write_executed": False,
    "serving_sqlite_opened_read_only": True,
    "serving_sqlite_write_or_rebuild_executed": False,
    "storage_write_executed": False,
    "binary_file_opened": False,
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


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def connect_serving_readonly(path: Path) -> sqlite3.Connection:
    recovery.reject_unbounded_d_root(path, "serving_db")
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def load_serving_profiles(serving_db: Path) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]], set[str], set[str]]:
    conn = connect_serving_readonly(serving_db)
    try:
        if not table_exists(conn, "dj_profile"):
            raise ValueError(f"serving db has no dj_profile table: {serving_db}")
        profiles: dict[str, dict[str, Any]] = {}
        by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in conn.execute(
            """
            SELECT dj_id, display_name, normalized_name, aliases_json, city_primary,
                   avatar_asset_id, event_count, collaborator_count, media_count
            FROM dj_profile
            """
        ):
            profile = {
                "dj_id": str(row["dj_id"] or ""),
                "display_name": str(row["display_name"] or ""),
                "normalized_name": str(row["normalized_name"] or ""),
                "city_primary": str(row["city_primary"] or ""),
                "avatar_asset_id_present": bool(row["avatar_asset_id"]),
                "event_count": int(row["event_count"] or 0),
                "collaborator_count": int(row["collaborator_count"] or 0),
                "media_count": int(row["media_count"] or 0),
            }
            profiles[profile["dj_id"]] = profile
            names = [profile["display_name"], profile["normalized_name"]]
            try:
                aliases = json.loads(row["aliases_json"] or "[]")
            except json.JSONDecodeError:
                aliases = []
            if isinstance(aliases, list):
                names.extend(str(alias) for alias in aliases)
            for name in names:
                normalized = normalize_name(name)
                if normalized:
                    by_name[normalized].append(profile)
        search_subject_ids: set[str] = set()
        if table_exists(conn, "search_document"):
            search_subject_ids = {
                str(row["subject_id"])
                for row in conn.execute("SELECT subject_id FROM search_document WHERE subject_type='dj'")
                if row["subject_id"]
            }
        graph_seed_ids: set[str] = set()
        if table_exists(conn, "graph_window_cache"):
            graph_seed_ids = {
                str(row["seed_subject_id"])
                for row in conn.execute("SELECT DISTINCT seed_subject_id FROM graph_window_cache")
                if row["seed_subject_id"]
            }
        return profiles, by_name, search_subject_ids, graph_seed_ids
    finally:
        conn.close()


def load_avatar_artifacts(manifest_dir: Path) -> dict[str, dict[str, Any]]:
    rows = recovery.read_jsonl(manifest_dir / "avatar_artifacts_manifest.jsonl", "avatar artifacts")
    return {recovery.stable_hash(row.get("avatar_id")): row for row in rows}


def load_rollups(manifest_dir: Path) -> dict[str, dict[str, Any]]:
    rows = recovery.read_jsonl(manifest_dir / "entity_rollups.jsonl", "entity rollups")
    return {str(row.get("eid") or ""): row for row in rows}


def unique_profiles(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for profile in profiles:
        dj_id = str(profile.get("dj_id") or "")
        if not dj_id or dj_id in seen:
            continue
        seen.add(dj_id)
        unique.append(profile)
    return unique


def bind_rows(
    storage_rows: list[dict[str, Any]],
    artifacts_by_avatar: dict[str, dict[str, Any]],
    rollups_by_eid: dict[str, dict[str, Any]],
    profiles_by_name: dict[str, list[dict[str, Any]]],
    search_subject_ids: set[str],
    graph_seed_ids: set[str],
    binary_source_ready: bool,
    storage_target_ready: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    ready_rows: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []
    for row in storage_rows:
        if not row.get("dj_first_candidate"):
            continue
        avatar_id_hash = str(row.get("avatar_id_hash") or "")
        artifact = artifacts_by_avatar.get(avatar_id_hash, {})
        eid = str(artifact.get("eid") or "")
        rollup = rollups_by_eid.get(eid, {})
        entity_name = str(rollup.get("entity_name") or artifact.get("entity_name") or "")
        normalized = normalize_name(entity_name)
        matches = unique_profiles(profiles_by_name.get(normalized, []))
        base = {
            "accepted_for_graph": False,
            "avatar_id_hash": avatar_id_hash,
            "avatar_url_sha256": row.get("avatar_url_sha256") or "",
            "binary_file_opened": False,
            "content_addressed_storage_key_hash": row.get("content_addressed_storage_key_hash") or "",
            "content_addressed_storage_key_preview": row.get("content_addressed_storage_key_preview") or "",
            "dj_first_candidate": True,
            "entity_kind": row.get("entity_kind") or "dj",
            "entity_name": entity_name,
            "entity_name_hash": row.get("entity_name_hash") or recovery.stable_hash(entity_name),
            "file_size_bytes": int(row.get("file_size_bytes") or 0),
            "local_file_sha256": row.get("local_file_sha256") or "",
            "memory_write_allowed": False,
            "platform": row.get("platform") or artifact.get("platform") or "unknown",
            "public_serving_field_allowed": False,
            "serving_rebuild_allowed": False,
            "source_raw_db_write_allowed": False,
            "storage_write_allowed_now": False,
            "write_execution_allowed_now": False,
        }
        blockers: list[str] = []
        if not entity_name:
            blockers.append("entity_name_missing_for_binding")
        if not matches:
            blockers.append("serving_dj_id_not_found_by_name_or_alias")
        if len(matches) > 1:
            blockers.append("serving_dj_id_ambiguous_by_name_or_alias")

        if len(matches) == 1:
            profile = matches[0]
            dj_id = str(profile["dj_id"])
            if dj_id not in search_subject_ids:
                blockers.append("serving_search_document_readback_missing")
            if dj_id not in graph_seed_ids:
                blockers.append("serving_graph_window_readback_missing")
        if len(matches) == 1 and not blockers:
            profile = matches[0]
            provenance_blockers = []
            if not binary_source_ready:
                provenance_blockers.append("explicit_binary_source_root_missing")
            if not storage_target_ready:
                provenance_blockers.append("explicit_storage_target_root_missing")
            ready = dict(base)
            ready.update(
                {
                    "avatar_entity_binding_status": "serving_dj_id_bound_report_only",
                    "blockers": sorted({"storage_write_gate_required", "public_display_gate_closed"} | set(provenance_blockers)),
                    "binding_selector_hash": recovery.stable_hash(
                        f"{avatar_id_hash}|{profile['dj_id']}|{row.get('local_file_sha256')}|{row.get('file_size_bytes')}",
                        24,
                    ),
                    "binary_source_provenance_ready": binary_source_ready,
                    "serving_city_primary": profile["city_primary"],
                    "serving_collaborator_count": profile["collaborator_count"],
                    "serving_display_name": profile["display_name"],
                    "serving_dj_id": profile["dj_id"],
                    "serving_dj_id_bound": True,
                    "serving_event_count": profile["event_count"],
                    "serving_existing_avatar_asset_present": profile["avatar_asset_id_present"],
                    "serving_graph_window_readback": True,
                    "serving_media_count": profile["media_count"],
                    "serving_search_document_readback": True,
                    "storage_target_provenance_ready": storage_target_ready,
                    "checksum_readback_required": True,
                    "rollback_selector_hash": recovery.stable_hash(f"rollback|{profile['dj_id']}|{avatar_id_hash}", 24),
                    "postwrite_readback_selector_hash": recovery.stable_hash(
                        f"postwrite|{profile['dj_id']}|{row.get('local_file_sha256')}", 24
                    ),
                }
            )
            ready_rows.append(ready)
            continue

        blocked = dict(base)
        blocked.update(
            {
                "avatar_entity_binding_status": "serving_dj_id_binding_blocked_report_only",
                "binary_source_provenance_ready": binary_source_ready,
                "blockers": sorted(set(blockers)),
                "candidate_serving_dj_ids": [profile["dj_id"] for profile in matches[:10]],
                "serving_dj_id_bound": False,
                "storage_target_provenance_ready": storage_target_ready,
            }
        )
        blocked_rows.append(blocked)

    duplicate_review_rows: list[dict[str, Any]] = []
    by_dj: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ready_rows:
        by_dj[str(row.get("serving_dj_id") or "")].append(row)
    for dj_id, rows in sorted(by_dj.items()):
        if len(rows) <= 1:
            continue
        selector_group_hash = recovery.stable_hash(
            {"dj_id": dj_id, "avatars": sorted(str(row.get("avatar_id_hash") or "") for row in rows)},
            24,
        )
        for row in rows:
            duplicate_review_rows.append(
                {
                    "accepted_for_graph": False,
                    "avatar_id_hash": row["avatar_id_hash"],
                    "binding_selector_hash": row["binding_selector_hash"],
                    "blockers": ["primary_avatar_selection_required"],
                    "entity_name": row["entity_name"],
                    "graph_write_allowed": False,
                    "local_file_sha256": row["local_file_sha256"],
                    "memory_write_allowed": False,
                    "platform": row["platform"],
                    "primary_avatar_selection_status": "duplicate_serving_dj_avatar_review_required_report_only",
                    "public_serving_field_allowed": False,
                    "selector_group_hash": selector_group_hash,
                    "serving_display_name": row["serving_display_name"],
                    "serving_dj_id": row["serving_dj_id"],
                    "serving_rebuild_allowed": False,
                    "source_raw_db_write_allowed": False,
                    "storage_write_allowed_now": False,
                    "write_execution_allowed_now": False,
                }
            )
    return ready_rows, blocked_rows, duplicate_review_rows


def write_report(path: Path, summary: dict[str, Any]) -> None:
    counts = summary["counts"]
    lines = [
        "# Atlas T6 Avatar Entity Binding Gate 20260527",
        "",
        f"Generated: `{summary['generated_at']}`",
        "",
        "## Decision",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- DJ-first input / bound / blocked rows: `{counts['dj_first_input_rows']}/{counts['serving_dj_id_bound_rows']}/{counts['binding_blocked_rows']}`",
        f"- Unique bound DJs: `{counts['unique_bound_serving_dj_ids']}`",
        f"- Duplicate primary-avatar review groups / rows: `{counts['duplicate_serving_dj_avatar_groups']}/{counts['primary_avatar_selection_review_rows']}`",
        f"- Storage binary source / target provenance ready rows: `{counts['binary_source_provenance_ready_rows']}/{counts['storage_target_provenance_ready_rows']}`",
        f"- Leak hits public URL / sensitive key / local path: `{summary['leak_scan']['public_url_hits']}/{summary['leak_scan']['sensitive_key_hits']}/{summary['leak_scan']['local_path_hits']}`",
        "",
        "## LLM Audit Finding",
        "",
        "- Avatar discovery is no longer blocked. The DJ-first subset can mostly bind to selected serving `dj_profile` by deterministic name/alias selectors.",
        "- This gate keeps writes closed because the upstream artifacts provide hash/size evidence but no explicit binary source root or storage object root provenance for checksum readback.",
        "- `DJ HEARTSTRING` remains unbound in the selected serving DB; duplicate candidates for one serving DJ require a primary-avatar selection rule before any public avatar field.",
        "",
        "## Boundary Truth",
        "",
        "- Opened only the selected serving SQLite in read-only mode.",
        "- Did not open avatar binaries, write storage, mutate source/raw DB, rebuild/write serving SQLite, mutate graph/vector/production/public state, upload huaidj.club, deploy CloudRun, upload/review mini-program, write memory, call network/OCR/model providers, use 9router, or scan D: roots.",
        "",
        "## Evidence",
        "",
        f"- Summary: `{summary['outputs']['summary_json']}`",
        f"- Contract: `{summary['outputs']['contract_json']}`",
        f"- Bound rows: `{summary['outputs']['ready_rows']}`",
        f"- Blocked rows: `{summary['outputs']['blocked_rows']}`",
        f"- Primary selection review rows: `{summary['outputs']['primary_selection_review_rows']}`",
        "",
        "## Next Resume Pointer",
        "",
        f"`{summary['next_resume_pointer']}`",
        "",
    ]
    recovery.write_text(path, "\n".join(lines))


def build(args: argparse.Namespace) -> dict[str, Any]:
    storage_dir = Path(args.storage_dir)
    manifest_dir = Path(args.manifest_dir)
    serving_db = Path(args.serving_db)
    out_dir = Path(args.out_dir)
    report_path = Path(args.report)
    binary_source_root = Path(args.binary_source_root) if args.binary_source_root else None
    storage_target_root = Path(args.storage_target_root) if args.storage_target_root else None

    storage_rows = recovery.read_jsonl(storage_dir / "avatar_storage_contract_ready_report_only.jsonl", "avatar storage rows")
    storage_summary = recovery.read_json(storage_dir / "avatar_storage_contract_summary.json", "avatar storage summary")
    artifacts_by_avatar = load_avatar_artifacts(manifest_dir)
    rollups_by_eid = load_rollups(manifest_dir)
    profiles, profiles_by_name, search_subject_ids, graph_seed_ids = load_serving_profiles(serving_db)

    if binary_source_root is not None:
        recovery.reject_unbounded_d_root(binary_source_root, "binary_source_root")
    if storage_target_root is not None:
        recovery.reject_unbounded_d_root(storage_target_root, "storage_target_root")
    binary_source_ready = bool(binary_source_root and binary_source_root.exists())
    storage_target_ready = bool(storage_target_root and storage_target_root.exists())

    ready_rows, blocked_rows, duplicate_review_rows = bind_rows(
        storage_rows,
        artifacts_by_avatar,
        rollups_by_eid,
        profiles_by_name,
        search_subject_ids,
        graph_seed_ids,
        binary_source_ready,
        storage_target_ready,
    )

    ready_path = out_dir / "avatar_entity_binding_ready_report_only.jsonl"
    blocked_path = out_dir / "avatar_entity_binding_blocked_rows.jsonl"
    duplicate_path = out_dir / "avatar_primary_selection_review_rows.jsonl"
    contract_path = out_dir / "avatar_entity_binding_contract.json"
    summary_path = out_dir / "avatar_entity_binding_summary.json"
    leak_path = out_dir / "leak_scan.json"
    summary_md_path = out_dir / "avatar_entity_binding_summary.md"

    unique_bound_ids = {str(row.get("serving_dj_id") or "") for row in ready_rows if row.get("serving_dj_id")}
    duplicate_groups = sum(1 for _, count in Counter(row.get("serving_dj_id") for row in ready_rows).items() if count > 1)
    counts = {
        "input_storage_ready_rows": len(storage_rows),
        "dj_first_input_rows": sum(1 for row in storage_rows if row.get("dj_first_candidate")),
        "serving_dj_id_bound_rows": len(ready_rows),
        "binding_blocked_rows": len(blocked_rows),
        "unique_bound_serving_dj_ids": len(unique_bound_ids),
        "serving_search_document_readback_rows": sum(1 for row in ready_rows if row.get("serving_search_document_readback")),
        "serving_graph_window_readback_rows": sum(1 for row in ready_rows if row.get("serving_graph_window_readback")),
        "duplicate_serving_dj_avatar_groups": duplicate_groups,
        "primary_avatar_selection_review_rows": len(duplicate_review_rows),
        "binary_source_provenance_ready_rows": sum(1 for row in ready_rows if row.get("binary_source_provenance_ready")),
        "storage_target_provenance_ready_rows": sum(1 for row in ready_rows if row.get("storage_target_provenance_ready")),
        "source_raw_db_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "storage_write_allowed_now_rows": 0,
        "memory_write_allowed_rows": 0,
        "serving_profile_rows": len(profiles),
    }

    contract = {
        "schema_version": f"{SCHEMA_VERSION}.contract",
        "generated_at": now_iso(),
        "decision": "atlas_t6_avatar_entity_binding_gate_partial_ready_storage_target_blocked_report_only",
        "report_only": True,
        "source_storage_decision": storage_summary.get("decision"),
        "binding_policy": {
            "entity_scope": "dj_first_only",
            "serving_selector": "unique normalized entity_name match against dj_profile display_name/normalized_name/aliases_json",
            "non_dj_rows_excluded_from_dj_avatar_display": True,
            "duplicate_serving_dj_requires_primary_avatar_selection": True,
            "raw_urls_emitted": False,
            "local_paths_emitted": False,
        },
        "storage_target_provenance": {
            "binary_source_root_provided": binary_source_root is not None,
            "binary_source_root_exists": binary_source_ready,
            "storage_target_root_provided": storage_target_root is not None,
            "storage_target_root_exists": storage_target_ready,
            "binary_source_root_hash": recovery.stable_hash(str(binary_source_root.resolve()) if binary_source_root else "", 24) if binary_source_root else "",
            "storage_target_root_hash": recovery.stable_hash(str(storage_target_root.resolve()) if storage_target_root else "", 24) if storage_target_root else "",
            "storage_write_allowed_now": False,
        },
        "prewrite_requirements": [
            "provide explicit bounded binary source root and storage target root without exposing local paths",
            "read each binary only after storage target provenance is explicit and verify local_file_sha256 plus file_size_bytes",
            "choose one primary avatar when multiple avatar rows bind to the same serving dj_id",
            "materialize prewrite snapshot of dj_profile.avatar_asset_id and media_count for each target dj_id",
            "write storage objects first, then rebuild a derived serving candidate; do not update public fields in-place",
        ],
        "postwrite_requirements": [
            "read back every storage object checksum and byte size",
            "read back every derived serving dj_profile.avatar_asset_id and media_count delta",
            "run local graph/search/detail UI/API smoke for bound DJs before public-serving approval",
            "keep rollback selectors for storage object removal and serving row inverse mapping",
        ],
        "write_guards": WRITE_GUARDS,
    }

    leak_scan = recovery.leak_counts_for(
        {
            "contract": contract,
            "ready_rows": ready_rows,
            "blocked_rows": blocked_rows,
            "primary_selection_review_rows": duplicate_review_rows,
        }
    )
    failed_checks: list[str] = []
    if blocked_rows:
        failed_checks.append("binding_blocked_rows_present")
    if duplicate_review_rows:
        failed_checks.append("primary_avatar_selection_review_required")
    if not binary_source_ready:
        failed_checks.append("binary_source_provenance_missing")
    if not storage_target_ready:
        failed_checks.append("storage_target_provenance_missing")
    if any(leak_scan.values()):
        failed_checks.append("leak_scan_hits_present")

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": contract["generated_at"],
        "decision": contract["decision"],
        "failed_checks": failed_checks,
        "counts": counts,
        "blocked_reason_counts_top": recovery.top_counts(Counter(blocker for row in blocked_rows for blocker in row.get("blockers", []))),
        "platform_counts_top": recovery.top_counts(Counter(str(row.get("platform") or "unknown") for row in ready_rows)),
        "leak_scan": leak_scan,
        "write_guards": WRITE_GUARDS,
        "inputs": {
            "storage_summary": recovery.display_path(storage_dir / "avatar_storage_contract_summary.json"),
            "storage_ready_rows": recovery.display_path(storage_dir / "avatar_storage_contract_ready_report_only.jsonl"),
            "v4_avatar_artifacts": recovery.display_path(manifest_dir / "avatar_artifacts_manifest.jsonl"),
            "v4_entity_rollups": recovery.display_path(manifest_dir / "entity_rollups.jsonl"),
            "selected_serving_db": recovery.display_path(serving_db),
        },
        "outputs": {
            "summary_json": recovery.display_path(summary_path),
            "contract_json": recovery.display_path(contract_path),
            "ready_rows": recovery.display_path(ready_path),
            "blocked_rows": recovery.display_path(blocked_path),
            "primary_selection_review_rows": recovery.display_path(duplicate_path),
            "summary_md": recovery.display_path(summary_md_path),
            "report": recovery.display_path(report_path),
        },
        "boundary_truth": {
            "serving_sqlite_opened_read_only": True,
            "binary_file_opened": False,
            "storage_write_executed": False,
            "source_raw_db_opened": False,
            "source_raw_db_write_executed": False,
            "serving_sqlite_write_or_rebuild_executed": False,
            "graph_vector_public_mutation_executed": False,
            "huaidj_club_upload_executed": False,
        },
        "next_resume_pointer": recovery.display_path(ready_path),
    }

    recovery.write_jsonl(ready_path, ready_rows)
    recovery.write_jsonl(blocked_path, blocked_rows)
    recovery.write_jsonl(duplicate_path, duplicate_review_rows)
    recovery.write_json(contract_path, contract)
    recovery.write_json(summary_path, summary)
    recovery.write_json(leak_path, leak_scan)
    recovery.write_text(summary_md_path, f"# Avatar Entity Binding Summary\n\nDecision: `{summary['decision']}`\n")
    write_report(report_path, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-dir", type=Path, default=DEFAULT_STORAGE_DIR)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--serving-db", type=Path, default=DEFAULT_SERVING_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--binary-source-root", type=Path)
    parser.add_argument("--storage-target-root", type=Path)
    return parser.parse_args()


def main() -> None:
    summary = build(parse_args())
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
