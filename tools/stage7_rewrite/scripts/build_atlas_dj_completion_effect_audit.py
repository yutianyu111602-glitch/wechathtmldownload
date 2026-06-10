#!/usr/bin/env python3
"""Audit DJ-first Atlas completion coverage and sidecar merge contract.

This is a report-only builder. It opens serving/source SQLite inputs read-only,
compares the selected DJ-first serving candidate with its base, and writes a
contract for later T6 outlink/avatar sidecar ingestion. It does not mutate
SQLite, graph/vector stores, CloudRun, public pointers, or memory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_BASE_SERVING_DB = REPO_ROOT / "reports" / "atlas_serving_activity_current_time_dedupe_strict_20260525-1625" / "atlas_serving.sqlite"
DEFAULT_CANDIDATE_DB = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "atlas_serving.sqlite"
DEFAULT_CANDIDATE_MANIFEST = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "manifest.json"
DEFAULT_SOURCE_RAW_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435"
    / "atlas.sqlite"
)
DEFAULT_MAPPING_SUMMARY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_source_raw_mapping_probe_q6_20260526"
    / "source_raw_mapping_probe_summary.json"
)
DEFAULT_WSL_SUPERVISOR = Path(r"\\wsl.localhost\Ubuntu\home\pc\scripts\atlas_outlink_supervisor_last.json")
DEFAULT_WSL_SCRATCH_DB = Path(r"\\wsl.localhost\Ubuntu\tmp\swarm_scratch.sqlite")
DEFAULT_SIDECAR_THREAD_ID = "codex://threads/019e5345-06e4-7fd2-84ca-00071e7e1ecb"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_dj_completion_effect_audit_t5_t6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_T6_DJ_COMPLETION_EFFECT_AND_SIDECAR_CONTRACT_20260526.md"
SCHEMA_VERSION = "stage7_atlas_dj_completion_effect_audit.v1"

URL_RE = re.compile(r"https?://|www\.", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization|bearer)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 800) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def display_path(path: Path | None) -> str:
    if not path:
        return ""
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except Exception:
        return path.name


def path_ref(path: Path | None) -> dict[str, Any]:
    if not path:
        return {"present": False}
    present = path.exists()
    raw = str(path)
    return {
        "present": present,
        "display": display_path(path),
        "basename": path.name,
        "path_sha256_12": hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:12],
        "bytes": path.stat().st_size if present and path.is_file() else 0,
    }


def reject_unbounded_d_root(path: Path, label: str) -> None:
    raw = str(path).replace("\\", "/").casefold()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"}:
        raise ValueError(f"{label} must not be an unbounded D: root: {path}")
    if raw.startswith("d:/ddownload") or raw.startswith("d:/aidata") or raw.startswith("/mnt/d/ddownload") or raw.startswith("/mnt/d/aidata"):
        raise ValueError(f"{label} must not scan cold D: data roots: {path}")


def read_json(path: Path | None, default: Any = None) -> Any:
    if not path:
        return default
    reject_unbounded_d_root(path, "json_input")
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))


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


def connect_readonly(path: Path) -> sqlite3.Connection:
    reject_unbounded_d_root(path, "sqlite_input")
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?", (table,)).fetchone() is not None


def scalar(conn: sqlite3.Connection, sql: str) -> int:
    return int(conn.execute(sql).fetchone()[0])


def pct(count: int, total: int) -> float:
    return round(count * 100.0 / total, 2) if total else 0.0


SERVING_TABLES = [
    "dj_profile",
    "performance_event",
    "dj_event",
    "dj_relation_rollup",
    "dj_venue_rollup",
    "canonical_subject",
    "search_document",
    "graph_window_cache",
    "activity_event_detail",
    "activity_evidence_ref",
]

SERVING_FIELDS: dict[str, list[tuple[str, str]]] = {
    "dj_profile": [
        ("display_name", "display_name IS NOT NULL AND trim(display_name)<>''"),
        ("aliases", "aliases_json IS NOT NULL AND trim(aliases_json) NOT IN ('','[]','{}')"),
        ("city_primary", "city_primary IS NOT NULL AND trim(city_primary)<>''"),
        ("avatar_asset_id", "avatar_asset_id IS NOT NULL AND trim(avatar_asset_id)<>''"),
        ("event_count_gt0", "coalesce(event_count,0)>0"),
        ("venue_count_gt0", "coalesce(venue_count,0)>0"),
        ("collaborator_count_gt0", "coalesce(collaborator_count,0)>0"),
        ("organization_count_gt0", "coalesce(organization_count,0)>0"),
        ("media_count_gt0", "coalesce(media_count,0)>0"),
        ("first_seen", "first_seen_at IS NOT NULL AND trim(first_seen_at)<>''"),
        ("last_seen", "last_seen_at IS NOT NULL AND trim(last_seen_at)<>''"),
    ],
    "performance_event": [
        ("event_title", "event_title IS NOT NULL AND trim(event_title)<>''"),
        ("starts_at", "starts_at IS NOT NULL AND trim(starts_at)<>''"),
        ("time_text", "time_text IS NOT NULL AND trim(time_text)<>''"),
        ("venue_name", "venue_name IS NOT NULL AND trim(venue_name)<>''"),
        ("city", "city IS NOT NULL AND trim(city)<>''"),
        ("source_ref", "source_ref_id IS NOT NULL AND trim(source_ref_id)<>''"),
        ("participant_count_gt0", "coalesce(participant_count,0)>0"),
        ("organizer_count_gt0", "coalesce(organizer_count,0)>0"),
    ],
    "dj_event": [
        ("starts_at", "starts_at IS NOT NULL AND trim(starts_at)<>''"),
        ("time_text", "time_text IS NOT NULL AND trim(time_text)<>''"),
        ("venue_name", "venue_name IS NOT NULL AND trim(venue_name)<>''"),
        ("city", "city IS NOT NULL AND trim(city)<>''"),
        ("source_ref", "source_ref_id IS NOT NULL AND trim(source_ref_id)<>''"),
    ],
    "dj_relation_rollup": [
        ("same_event", "coalesce(same_event_count,0)>0"),
        ("same_venue", "coalesce(same_venue_count,0)>0"),
        ("same_source_context", "coalesce(same_source_context_count,0)>0"),
        ("relation_label", "relation_label_zh IS NOT NULL AND trim(relation_label_zh)<>''"),
        ("sample_evidence", "sample_evidence_json IS NOT NULL AND trim(sample_evidence_json) NOT IN ('','[]','{}')"),
    ],
    "dj_venue_rollup": [
        ("venue_name", "venue_name IS NOT NULL AND trim(venue_name)<>''"),
        ("city", "city IS NOT NULL AND trim(city)<>''"),
        ("event_count_gt0", "coalesce(event_count,0)>0"),
    ],
    "search_document": [
        ("display_name", "display_name IS NOT NULL AND trim(display_name)<>''"),
        ("search_text", "search_text IS NOT NULL AND trim(search_text)<>''"),
        ("public_state", "public_state IS NOT NULL AND trim(public_state)<>''"),
    ],
    "graph_window_cache": [
        ("nodes_json", "nodes_json IS NOT NULL AND trim(nodes_json) NOT IN ('','[]','{}')"),
        ("edges_json", "edges_json IS NOT NULL AND trim(edges_json) NOT IN ('','[]','{}')"),
    ],
}

SOURCE_FIELDS: dict[str, list[tuple[str, str]]] = {
    "articles": [
        ("title", "title IS NOT NULL AND trim(title)<>''"),
        ("publish_time", "publish_time IS NOT NULL AND trim(publish_time)<>''"),
        ("source_account", "source_account IS NOT NULL AND trim(source_account)<>''"),
        ("event_count_gt0", "coalesce(event_count,0)>0"),
        ("entity_count_gt0", "coalesce(entity_count,0)>0"),
        ("vector_text_preview", "vector_text_preview IS NOT NULL AND trim(vector_text_preview)<>''"),
    ],
    "events": [
        ("name", "name IS NOT NULL AND trim(name)<>''"),
        ("place", "place IS NOT NULL AND trim(place)<>''"),
        ("city", "city IS NOT NULL AND trim(city)<>''"),
        ("time_iso", "time_iso IS NOT NULL AND trim(time_iso)<>''"),
        ("time_text", "time_text IS NOT NULL AND trim(time_text)<>''"),
        ("participants_json", "participants_json IS NOT NULL AND trim(participants_json) NOT IN ('','[]','{}')"),
        ("organizers_json", "organizers_json IS NOT NULL AND trim(organizers_json) NOT IN ('','[]','{}')"),
        ("vector_text_preview", "vector_text_preview IS NOT NULL AND trim(vector_text_preview)<>''"),
    ],
    "entities": [
        ("name", "name IS NOT NULL AND trim(name)<>''"),
        ("type", "type IS NOT NULL AND trim(type)<>''"),
        ("city", "city IS NOT NULL AND trim(city)<>''"),
        ("aliases", "aliases_json IS NOT NULL AND trim(aliases_json) NOT IN ('','[]','{}')"),
        ("bio", "bio IS NOT NULL AND trim(bio)<>''"),
        ("evidence_quote", "evidence_quote IS NOT NULL AND trim(evidence_quote)<>''"),
        ("vector_text_preview", "vector_text_preview IS NOT NULL AND trim(vector_text_preview)<>''"),
    ],
    "atlas_activity_events": [
        ("title", "title IS NOT NULL AND trim(title)<>''"),
        ("event_date_start", "event_date_start IS NOT NULL AND trim(event_date_start)<>''"),
        ("event_time_text", "event_time_text IS NOT NULL AND trim(event_time_text)<>''"),
        ("venue_name", "venue_name IS NOT NULL AND trim(venue_name)<>''"),
        ("city_name", "city_name IS NOT NULL AND trim(city_name)<>''"),
        ("lineup_artists", "lineup_artists_json IS NOT NULL AND trim(lineup_artists_json) NOT IN ('','[]','{}')"),
    ],
}


def table_count(conn: sqlite3.Connection, table: str) -> int:
    return scalar(conn, f"SELECT COUNT(*) FROM {table}") if table_exists(conn, table) else 0


def coverage_for(conn: sqlite3.Connection, fields: dict[str, list[tuple[str, str]]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for table, specs in fields.items():
        if not table_exists(conn, table):
            result[table] = {"rows": 0, "missing_table": True, "fields": {}}
            continue
        total = table_count(conn, table)
        field_payload: dict[str, Any] = {}
        for field_name, condition in specs:
            count = scalar(conn, f"SELECT COUNT(*) FROM {table} WHERE {condition}")
            field_payload[field_name] = {
                "non_empty": count,
                "missing": max(total - count, 0),
                "pct": pct(count, total),
            }
        result[table] = {"rows": total, "fields": field_payload}
    return result


def serving_table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {table: table_count(conn, table) for table in SERVING_TABLES}


def compare_coverage(base: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table, cand_payload in candidate.items():
        base_payload = base.get(table, {"rows": 0, "fields": {}})
        for field_name, cand_field in cand_payload.get("fields", {}).items():
            base_field = base_payload.get("fields", {}).get(field_name, {"non_empty": 0, "missing": base_payload.get("rows", 0), "pct": 0.0})
            rows.append(
                {
                    "table": table,
                    "field": field_name,
                    "base_non_empty": base_field["non_empty"],
                    "candidate_non_empty": cand_field["non_empty"],
                    "delta_non_empty": cand_field["non_empty"] - base_field["non_empty"],
                    "candidate_missing": cand_field["missing"],
                    "candidate_pct": cand_field["pct"],
                    "base_pct": base_field["pct"],
                    "delta_pct": round(cand_field["pct"] - base_field["pct"], 2),
                }
            )
    return rows


def top_rows(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    payload: dict[str, list[dict[str, Any]]] = {}
    if table_exists(conn, "performance_event"):
        payload["sample_events"] = [
            dict(row)
            for row in conn.execute(
                """
                SELECT event_id, event_title, starts_at, time_text, venue_name, city
                FROM performance_event
                ORDER BY event_id
                LIMIT 50
                """
            )
        ]
        payload["top_cities"] = [
            dict(row)
            for row in conn.execute(
                """
                SELECT city, COUNT(*) AS event_count
                FROM performance_event
                WHERE city IS NOT NULL AND trim(city)<>''
                GROUP BY city
                ORDER BY event_count DESC, city
                LIMIT 20
                """
            )
        ]
        payload["top_venues"] = [
            dict(row)
            for row in conn.execute(
                """
                SELECT venue_name, city, COUNT(*) AS event_count
                FROM performance_event
                WHERE venue_name IS NOT NULL AND trim(venue_name)<>''
                GROUP BY venue_name, city
                ORDER BY event_count DESC, venue_name
                LIMIT 20
                """
            )
        ]
    if table_exists(conn, "dj_profile"):
        payload["top_djs_by_events"] = [
            dict(row)
            for row in conn.execute(
                """
                SELECT display_name, event_count, venue_count, collaborator_count, organization_count, first_seen_at, last_seen_at
                FROM dj_profile
                ORDER BY event_count DESC, display_name
                LIMIT 20
                """
            )
        ]
    return payload


def leak_hits_for_payload(payload: Any) -> dict[str, int]:
    hits = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}

    def visit(value: Any, key: str = "") -> None:
        if SECRET_RE.search(key):
            hits["sensitive_key_hits"] += 1
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(child_value, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str):
            hits["public_url_hits"] += len(URL_RE.findall(value))
            hits["sensitive_key_hits"] += len(SECRET_RE.findall(value))
            hits["local_path_hits"] += len(LOCAL_PATH_RE.findall(value))

    visit(payload)
    return hits


def add_hits(total: dict[str, int], payload: Any) -> None:
    hits = leak_hits_for_payload(payload)
    for key, value in hits.items():
        total[key] += value


def sanitized_wsl_supervisor(path: Path | None) -> dict[str, Any]:
    data = read_json(path, {}) if path else {}
    report = data.get("report") if isinstance(data, dict) else {}
    if not isinstance(report, dict):
        report = {}
    safety = report.get("safety") if isinstance(report.get("safety"), dict) else {}
    return {
        "artifact_ref": path_ref(path),
        "gate": compact(data.get("gate"), 120) if isinstance(data, dict) else "",
        "detail": compact(data.get("detail"), 160) if isinstance(data, dict) else "",
        "status": compact(report.get("status"), 80),
        "processed": int(report.get("processed") or 0),
        "total": int(report.get("total") or 0),
        "remaining": int(report.get("remaining") or 0),
        "progress_pct": float(report.get("progress_pct") or 0.0),
        "age_min_at_probe": float(report.get("age_min") or 0.0),
        "safety": {
            "report_only": bool(safety.get("report_only", False)),
            "no_9router": bool(safety.get("no_9router", False)),
            "no_cookie_or_token_export": bool(safety.get("no_cookie_or_token_export", False)),
            "no_graph_vector_sqlite_mem0_write": bool(safety.get("no_graph_vector_sqlite_mem0_write", False)),
            "no_cloudrun_or_miniprogram_action": bool(safety.get("no_cloudrun_or_miniprogram_action", False)),
        },
    }


def sqlite_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    if not table_exists(conn, table):
        return []
    return [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def inspect_scratch_sqlite(path: Path) -> dict[str, Any]:
    target_tables = ["dj_social_profiles", "dj_outlinks", "dj_identity_candidates", "dj_avatars"]
    conn = connect_readonly(path)
    try:
        table_counts = {table: table_count(conn, table) for table in target_tables}
        column_shapes = {table: sqlite_columns(conn, table) for table in target_tables if table_exists(conn, table)}
    finally:
        conn.close()

    flattened_columns = {column for columns in column_shapes.values() for column in columns}
    raw_url_columns = sorted(column for column in flattened_columns if "url" in column.lower())
    raw_path_columns = sorted(column for column in flattened_columns if "path" in column.lower())
    return {
        "status": "read_only_shape_checked",
        "table_counts": table_counts,
        "raw_url_columns_present": raw_url_columns,
        "local_path_columns_present": raw_path_columns,
        "merge_readiness": "blocked_until_hash_redacted_manifest_and_leak_scan_exist"
        if raw_url_columns or raw_path_columns
        else "shape_ready_for_manifest_validation",
    }


def inspect_wsl_scratch_db(path: Path | None) -> dict[str, Any]:
    if not path:
        return {"artifact_ref": path_ref(path), "status": "not_configured"}
    reject_unbounded_d_root(path, "wsl_scratch_db")
    if not path.exists():
        return {"artifact_ref": path_ref(path), "status": "missing"}

    # SQLite URI read-only mode rejects WSL UNC authorities on Windows. Copying a
    # bounded scratch DB to a temp snapshot preserves source DB immutability.
    if str(path).startswith("\\\\"):
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = Path(tmpdir) / "wsl_scratch_snapshot.sqlite"
            shutil.copy2(path, snapshot)
            result = inspect_scratch_sqlite(snapshot)
            result["snapshot_mode"] = "temporary_copy_from_wsl_unc"
    else:
        result = inspect_scratch_sqlite(path)
        result["snapshot_mode"] = "direct_read_only"
    result["artifact_ref"] = path_ref(path)
    return result


def sidecar_contract(sidecar_thread_id: str = DEFAULT_SIDECAR_THREAD_ID) -> dict[str, Any]:
    fields = {
        "manifest.json": [
            "schema_version",
            "producer",
            "run_id",
            "generated_at",
            "input_entity_count",
            "candidate_count",
            "avatar_artifact_count",
            "blocked_count",
            "leak_scan",
            "write_guards",
        ],
        "entity_rollups.jsonl": [
            "entity_id",
            "entity_kind",
            "display_name",
            "normalized_name",
            "candidate_counts_by_kind",
            "best_profile_url_hash",
            "best_avatar_asset_hash",
            "source_context_hashes",
            "merge_status",
            "blockers",
        ],
        "candidate_evidence.jsonl": [
            "candidate_id",
            "entity_id",
            "candidate_kind",
            "platform",
            "host",
            "handle",
            "url_sha256",
            "url_redacted",
            "canonical_url_key",
            "source_context_hashes",
            "identity_match_signals",
            "evidence_text_summary",
            "evidence_text_hash",
            "confidence",
            "blocked_reason",
        ],
        "avatar_artifacts_manifest.jsonl": [
            "avatar_asset_id",
            "entity_id",
            "candidate_id",
            "content_sha256",
            "mime_type",
            "byte_size",
            "width",
            "height",
            "storage_ref_hash",
            "perceptual_hash",
            "download_status",
            "blocked_reason",
        ],
        "blocked_rows.jsonl": ["entity_id", "candidate_id", "blocked_stage", "blocked_reason", "required_next_evidence"],
        "leak_scan.json": ["public_url_hits", "sensitive_key_hits", "local_path_hits", "sample_count"],
        "provenance_summary.json": ["source_inputs", "source_input_hashes", "runtime", "safety", "counts"],
    }
    return {
        "schema_version": "stage7_atlas_t6_outlink_avatar_sidecar_contract.v1",
        "purpose": "T6 produces report-only outlink/profile/avatar evidence for T5 DJ-first Atlas merge validation.",
        "producer_thread_ref": sidecar_thread_id,
        "required_outputs": fields,
        "row_invariants": {
            "raw_url_must_not_be_emitted": True,
            "url_sha256_required_for_url_candidates": True,
            "source_context_hash_required_before_identity_promotion": True,
            "avatar_binary_must_have_content_sha256": True,
            "avatar_storage_ref_must_be_hashed_or_report_local": True,
            "entity_join_must_target_existing_serving_or_source_entity": True,
            "duplicate_canonical_url_key_must_be_deduped": True,
            "accepted_for_graph_default": False,
            "source_sqlite_write_allowed_default": False,
            "serving_rebuild_allowed_default": False,
            "graph_write_allowed_default": False,
            "public_serving_field_allowed_default": False,
            "memory_write_allowed_default": False,
        },
        "t5_merge_preconditions": [
            "schema_parse_passed",
            "manifest_counts_match_jsonl_counts",
            "leak_scan_public_url_sensitive_key_local_path_hits_zero",
            "every_candidate_has_entity_join_and_source_context_status",
            "avatar_artifacts_have_hash_mime_size_and_optional_dimensions",
            "profile_candidates_are_review_inputs_not_identity_proof",
            "source_raw_or_serving_merge_gate_records_prewrite_snapshot_rollback_and_postwrite_readback",
        ],
        "promotion_boundary": {
            "t6_may_write": "report-local evidence only",
            "t5_must_validate_before": "source/raw DB mutation, serving rebuild, graph/vector write, public state, memory",
            "huaidj_club_upload": "disabled for this run by user instruction",
        },
    }


def build_packet(
    base_serving_db: Path,
    candidate_db: Path,
    source_raw_db: Path | None,
    candidate_manifest: Path | None,
    mapping_summary: Path | None,
    wsl_supervisor: Path | None,
    out_dir: Path,
    report_path: Path,
    wsl_scratch_db: Path | None = None,
    sidecar_thread_id: str = DEFAULT_SIDECAR_THREAD_ID,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    leak_counts = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}
    failed_checks: list[str] = []

    with connect_readonly(base_serving_db) as base_conn, connect_readonly(candidate_db) as candidate_conn:
        base_counts = serving_table_counts(base_conn)
        candidate_counts = serving_table_counts(candidate_conn)
        base_coverage = coverage_for(base_conn, SERVING_FIELDS)
        candidate_coverage = coverage_for(candidate_conn, SERVING_FIELDS)
        coverage_delta = compare_coverage(base_coverage, candidate_coverage)
        top_samples = top_rows(candidate_conn)

    source_coverage: dict[str, Any] = {}
    source_counts: dict[str, int] = {}
    source_raw_present = bool(source_raw_db and source_raw_db.exists())
    if source_raw_db and source_raw_present:
        with connect_readonly(source_raw_db) as source_conn:
            source_coverage = coverage_for(source_conn, SOURCE_FIELDS)
            source_counts = {table: table_count(source_conn, table) for table in SOURCE_FIELDS if table_exists(source_conn, table)}

    manifest = read_json(candidate_manifest, {}) if candidate_manifest else {}
    mapping = read_json(mapping_summary, {}) if mapping_summary else {}
    wsl_status = sanitized_wsl_supervisor(wsl_supervisor) if wsl_supervisor and wsl_supervisor.exists() else {"artifact_ref": path_ref(wsl_supervisor), "status": "missing"}
    wsl_scratch_status = inspect_wsl_scratch_db(wsl_scratch_db)
    contract = sidecar_contract(sidecar_thread_id)

    gap_register = [
        row
        for row in coverage_delta
        if row["candidate_missing"] > 0
        and row["table"] in {"dj_profile", "performance_event", "dj_event", "dj_venue_rollup"}
        and row["field"] in {"avatar_asset_id", "media_count_gt0", "city_primary", "starts_at", "venue_name", "city"}
    ]
    gap_register.sort(key=lambda row: (row["table"], row["field"]))

    table_delta = {
        table: candidate_counts.get(table, 0) - base_counts.get(table, 0)
        for table in sorted(set(base_counts) | set(candidate_counts))
    }

    if candidate_counts.get("dj_profile", 0) <= base_counts.get("dj_profile", 0):
        failed_checks.append("dj_profile_delta_not_positive")
    if candidate_counts.get("dj_event", 0) <= base_counts.get("dj_event", 0):
        failed_checks.append("dj_event_delta_not_positive")
    if not source_raw_present:
        failed_checks.append("source_raw_db_not_available_for_merge_audit")

    # Leak-scan only public report payloads. Internal exact local paths are kept out of payloads.
    scan_payloads = [candidate_counts, base_counts, candidate_coverage, source_coverage, top_samples, wsl_status, wsl_scratch_status, contract]
    for payload in scan_payloads:
        add_hits(leak_counts, payload)
    if any(leak_counts.values()):
        failed_checks.append("audit_payload_leak_scan_hits")

    counts = {
        "base": base_counts,
        "candidate": candidate_counts,
        "delta": table_delta,
        "source_raw": source_counts,
        "mapped_manual_candidate_rows": int(mapping.get("counts", {}).get("ready_rows") or 0) if isinstance(mapping, dict) else 0,
        "mapped_unique_raw_event_row_pks": int(mapping.get("counts", {}).get("unique_selected_raw_event_row_pks") or 0) if isinstance(mapping, dict) else 0,
        "wsl_outlink_processed": int(wsl_status.get("processed") or 0),
        "wsl_outlink_remaining": int(wsl_status.get("remaining") or 0),
    }

    decision = "atlas_dj_completion_effect_audit_ready_report_only" if not failed_checks else "atlas_dj_completion_effect_audit_blocked_report_only"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "failed_checks": failed_checks,
        "counts": counts,
        "paths": {
            "base_serving_db": path_ref(base_serving_db),
            "candidate_db": path_ref(candidate_db),
            "source_raw_db": path_ref(source_raw_db),
            "candidate_manifest": path_ref(candidate_manifest),
            "mapping_summary": path_ref(mapping_summary),
            "wsl_supervisor": path_ref(wsl_supervisor),
            "wsl_scratch_db": path_ref(wsl_scratch_db),
        },
        "previous_sidecar_thread_ref": sidecar_thread_id,
        "candidate_manifest_decision": compact(manifest.get("decision"), 160) if isinstance(manifest, dict) else "",
        "source_raw_mapping_decision": compact(mapping.get("decision"), 160) if isinstance(mapping, dict) else "",
        "coverage": {
            "base": base_coverage,
            "candidate": candidate_coverage,
            "delta_rows": coverage_delta,
            "open_gap_register": gap_register,
        },
        "source_raw_coverage": source_coverage,
        "top_samples": top_samples,
        "wsl_sidecar_status": wsl_status,
        "wsl_scratch_shape_status": wsl_scratch_status,
        "t6_outlink_avatar_contract": contract,
        "leak_counts": leak_counts,
        "write_guards": {
            "report_only": True,
            "source_raw_db_opened_read_only": source_raw_present,
            "source_sqlite_write_executed": False,
            "serving_sqlite_write_executed": False,
            "serving_rebuild_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "public_pointer_updated": False,
            "huaidj_club_upload_executed": False,
            "memory_write_executed": False,
        },
        "next_resume_pointer": "tools/stage7_rewrite/reports/atlas_dj_completion_effect_audit_t5_t6_20260526/dj_completion_gap_register.jsonl",
    }

    write_json(out_dir / "dj_completion_effect_audit_summary.json", summary)
    write_json(out_dir / "dj_completion_coverage_comparison.json", {"coverage_delta_rows": coverage_delta})
    write_jsonl(out_dir / "dj_completion_gap_register.jsonl", gap_register)
    write_json(out_dir / "t6_outlink_avatar_sidecar_contract.json", contract)
    write_text(out_dir / "t6_outlink_avatar_sidecar_contract.md", render_contract_md(contract))
    write_text(report_path, render_report(summary))
    return summary


def render_contract_md(contract: dict[str, Any]) -> str:
    lines = [
        "# T6 Outlink / Avatar Sidecar Contract",
        "",
        f"- schema_version: `{contract['schema_version']}`",
        f"- purpose: {contract['purpose']}",
        f"- producer_thread_ref: `{contract.get('producer_thread_ref', '')}`",
        "",
        "## Required Outputs",
        "",
    ]
    for name, fields in contract["required_outputs"].items():
        lines.append(f"- `{name}`: {', '.join(f'`{field}`' for field in fields)}")
    lines.extend(
        [
            "",
            "## Invariants",
            "",
        ]
    )
    for key, value in contract["row_invariants"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## T5 Merge Preconditions", ""])
    for item in contract["t5_merge_preconditions"]:
        lines.append(f"- `{item}`")
    lines.extend(["", "## Promotion Boundary", ""])
    for key, value in contract["promotion_boundary"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    return "\n".join(lines)


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    candidate = counts["candidate"]
    delta = counts["delta"]
    leak = summary["leak_counts"]
    gaps = summary["coverage"]["open_gap_register"]
    wsl = summary["wsl_sidecar_status"]
    scratch = summary.get("wsl_scratch_shape_status", {})
    lines = [
        "# Atlas T5/T6 DJ Completion Effect Audit And Sidecar Contract",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- failed_checks: `{summary['failed_checks']}`",
        f"- previous_sidecar_thread_ref: `{summary.get('previous_sidecar_thread_ref', '')}`",
        f"- candidate_manifest_decision: `{summary['candidate_manifest_decision']}`",
        f"- source_raw_mapping_decision: `{summary['source_raw_mapping_decision']}`",
        "",
        "## DJ-First Candidate Effect",
        "",
        f"- DJ profiles: `{candidate.get('dj_profile', 0)}` (`{delta.get('dj_profile', 0):+d}` vs base).",
        f"- Performance events: `{candidate.get('performance_event', 0)}` (`{delta.get('performance_event', 0):+d}` vs base).",
        f"- DJ-event edges: `{candidate.get('dj_event', 0)}` (`{delta.get('dj_event', 0):+d}` vs base).",
        f"- Directed DJ relations: `{candidate.get('dj_relation_rollup', 0)}` (`{delta.get('dj_relation_rollup', 0):+d}` vs base).",
        f"- Search docs / graph windows: `{candidate.get('search_document', 0)}` / `{candidate.get('graph_window_cache', 0)}`.",
        f"- Mapped manual merge candidates: `{counts['mapped_manual_candidate_rows']}` rows, `{counts['mapped_unique_raw_event_row_pks']}` raw event row pks.",
        "",
        "## Coverage Highlights",
        "",
    ]
    for table, fields in [
        ("dj_profile", ["display_name", "city_primary", "avatar_asset_id", "event_count_gt0", "venue_count_gt0", "collaborator_count_gt0", "first_seen"]),
        ("performance_event", ["starts_at", "time_text", "venue_name", "city", "participant_count_gt0"]),
        ("dj_event", ["starts_at", "venue_name", "city", "source_ref"]),
        ("dj_relation_rollup", ["same_event", "same_venue", "same_source_context", "relation_label", "sample_evidence"]),
        ("dj_venue_rollup", ["venue_name", "city", "event_count_gt0"]),
    ]:
        payload = summary["coverage"]["candidate"].get(table, {})
        total = payload.get("rows", 0)
        lines.append(f"### `{table}` rows `{total}`")
        for field in fields:
            metric = payload.get("fields", {}).get(field, {})
            lines.append(
                f"- `{field}`: `{metric.get('non_empty', 0)}/{total}` "
                f"({metric.get('pct', 0.0)}%), missing `{metric.get('missing', 0)}`"
            )
        lines.append("")
    lines.extend(
        [
            "## Open Gaps For New Atlas DB Merge",
            "",
        ]
    )
    for row in gaps[:30]:
        lines.append(
            f"- `{row['table']}.{row['field']}`: candidate pct `{row['candidate_pct']}%`, "
            f"missing `{row['candidate_missing']}`, delta non-empty `{row['delta_non_empty']}`."
        )
    if not gaps:
        lines.append("- No tracked open gap rows.")
    lines.extend(
        [
            "",
            "## WSL2 Sidecar Status",
            "",
            f"- supervisor gate/status: `{wsl.get('gate', '')}` / `{wsl.get('status', '')}`.",
            f"- outlink post-filter processed/total/remaining: `{wsl.get('processed', 0)}/{wsl.get('total', 0)}/{wsl.get('remaining', 0)}`.",
            f"- scratch DB status: `{scratch.get('status', '')}`; table_counts `{scratch.get('table_counts', {})}`.",
            f"- scratch raw URL/path columns: `{scratch.get('raw_url_columns_present', [])}` / `{scratch.get('local_path_columns_present', [])}`.",
            f"- scratch merge_readiness: `{scratch.get('merge_readiness', '')}`.",
            "- Avatar/profile sidecar output is contract input only until manifest counts, content hashes, entity joins, and leak scans pass.",
            "",
            "## Contract",
            "",
            "- Contract JSON: `tools/stage7_rewrite/reports/atlas_dj_completion_effect_audit_t5_t6_20260526/t6_outlink_avatar_sidecar_contract.json`.",
            "- Contract Markdown: `tools/stage7_rewrite/reports/atlas_dj_completion_effect_audit_t5_t6_20260526/t6_outlink_avatar_sidecar_contract.md`.",
            "- Required promotion boundary: T6 report-local only; T5 validates schema/entity joins/hash manifests before source/raw DB merge or serving rebuild.",
            "",
            "## Safety",
            "",
            f"- leak_counts: public_url/sensitive_key/local_path `{leak['public_url_hits']}/{leak['sensitive_key_hits']}/{leak['local_path_hits']}`.",
        ]
    )
    for key, value in summary["write_guards"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", f"- next_resume_pointer: `{summary['next_resume_pointer']}`", ""])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-serving-db", type=Path, default=DEFAULT_BASE_SERVING_DB)
    parser.add_argument("--candidate-db", type=Path, default=DEFAULT_CANDIDATE_DB)
    parser.add_argument("--source-raw-db", type=Path, default=DEFAULT_SOURCE_RAW_DB)
    parser.add_argument("--candidate-manifest", type=Path, default=DEFAULT_CANDIDATE_MANIFEST)
    parser.add_argument("--mapping-summary", type=Path, default=DEFAULT_MAPPING_SUMMARY)
    parser.add_argument("--wsl-supervisor", type=Path, default=DEFAULT_WSL_SUPERVISOR)
    parser.add_argument("--wsl-scratch-db", type=Path, default=DEFAULT_WSL_SCRATCH_DB)
    parser.add_argument("--sidecar-thread-id", default=DEFAULT_SIDECAR_THREAD_ID)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(
        args.base_serving_db,
        args.candidate_db,
        args.source_raw_db,
        args.candidate_manifest,
        args.mapping_summary,
        args.wsl_supervisor,
        args.out_dir,
        args.report,
        args.wsl_scratch_db,
        args.sidecar_thread_id,
    )
    print(json.dumps({"decision": summary["decision"], "failed_checks": summary["failed_checks"], "summary": str(args.out_dir / "dj_completion_effect_audit_summary.json")}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
