#!/usr/bin/env python3
"""Build the T6 avatar/media recovery packet for the v4 sidecar manifest.

This report-only packet consumes the hash/redacted WSL2 sidecar v4 manifest and
the current report-local social read-model UI contract. It validates avatar
hash/addressability, separates DJ-first candidates from venue/label/event
avatars, and leaves all storage, serving, graph, public, and memory writes
closed until a later explicit gate supplies target provenance and readback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_MANIFEST_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_redacted_manifest_20260526_v4"
DEFAULT_RENDERED_UI_CONTRACT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t6_sidecar_social_read_model_rendered_ui_smoke_t5_t6_20260527"
    / "social_read_model_rendered_ui_contract.json"
)
DEFAULT_OLD_VALIDATION_SUMMARY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t6_sidecar_manifest_validation_gate_t5_t6_20260526"
    / "sidecar_manifest_validation_summary.json"
)
DEFAULT_COMPLETION_ROLLUP_SUMMARY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_dj_completion_overlay_rollup_t5_t6_20260527"
    / "dj_completion_overlay_rollup_summary.json"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_avatar_media_recovery_packet_20260527"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_AVATAR_MEDIA_RECOVERY_PACKET_20260527.md"
SCHEMA_VERSION = "stage7_atlas_t6_avatar_media_recovery_packet.v1"
INPUT_SCHEMA_VERSION = "stage7_atlas_t6_sidecar_redacted_manifest.v1"

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
HASH64_RE = re.compile(r"^[0-9a-f]{64}$", re.I)
SAFE_METRIC_KEYS = {
    "public_url_hits",
    "sensitive_key_hits",
    "local_path_hits",
    "raw_url_hits",
    "redacted_url_reference_rows",
}
WRITE_GUARDS = {
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


def stable_hash(value: Any, length: int = 16) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="replace")).hexdigest()[:length]


def reject_unbounded_d_root(path: Path, label: str) -> None:
    raw = str(path).replace("\\", "/").casefold()
    resolved = raw
    try:
        resolved = str(path.resolve()).replace("\\", "/").casefold()
    except OSError:
        pass
    for value in {raw, resolved}:
        if value in {"d:", "d:/", "/mnt/d", "/mnt/d/"}:
            raise ValueError(f"{label} must not be an unbounded D: root: {path}")
        if value.startswith("d:/ddownload") or value.startswith("d:/aidata") or value.startswith("/mnt/d/ddownload") or value.startswith("/mnt/d/aidata"):
            raise ValueError(f"{label} must not scan cold D: data roots: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def read_json(path: Path, label: str) -> Any:
    reject_unbounded_d_root(path, label)
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        return json.load(handle)


def read_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    reject_unbounded_d_root(path, label)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, dict):
                raise ValueError(f"{label} line {line_no} is not an object")
            rows.append(row)
    return rows


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


def is_redacted_url(value: str) -> bool:
    return "[REDACTED]" in value or "REDACTED" in value


def leak_counts_for(payload: Any) -> dict[str, int]:
    counts = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}

    def visit(value: Any, key: str = "") -> None:
        if key not in SAFE_METRIC_KEYS and SECRET_KEY_RE.search(key):
            counts["sensitive_key_hits"] += 1
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(child_value, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str):
            if URL_RE.search(value) and not is_redacted_url(value):
                counts["public_url_hits"] += len(URL_RE.findall(value))
            counts["sensitive_key_hits"] += len(SECRET_VALUE_RE.findall(value))
            counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(value))

    visit(payload)
    return counts


def add_leak_counts(total: dict[str, int], payload: Any) -> None:
    hits = leak_counts_for(payload)
    for key, value in hits.items():
        total[key] += value


def top_counts(counter: Counter[str], limit: int = 10) -> list[dict[str, Any]]:
    return [{"value": key, "count": value} for key, value in counter.most_common(limit)]


def short_hash(value: Any) -> str:
    text = str(value or "")
    if HASH64_RE.match(text):
        return text[:16]
    return stable_hash(text, 16)


def build_avatar_rows(avatar_rows: list[dict[str, Any]], rollups_by_eid: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    recovery_rows: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []
    for row in avatar_rows:
        eid = str(row.get("eid") or "")
        rollup = rollups_by_eid.get(eid, {})
        entity_kind = str(rollup.get("entity_kind") or "missing_rollup")
        entity_type = str(rollup.get("entity_type") or "missing_rollup")
        local_hash = str(row.get("local_file_sha256") or "")
        url_hash = str(row.get("avatar_url_sha256") or "")
        file_size = int(row.get("file_size_bytes") or 0)
        hash_addressable = bool(HASH64_RE.match(local_hash)) and file_size > 0
        dj_first_candidate = entity_kind == "dj" and entity_type == "person"
        blockers: list[str] = ["serving_dj_id_binding_required", "storage_materialization_contract_required", "public_display_gate_closed"]
        if not hash_addressable:
            blockers.append("binary_hash_or_size_missing")
        if not rollup:
            blockers.append("entity_rollup_missing")
        if rollup and not dj_first_candidate:
            blockers.append("non_dj_entity_scope_review_required")

        if not hash_addressable:
            status = "binary_or_storage_contract_blocked_report_only"
        elif not rollup:
            status = "entity_rollup_missing_review_required_report_only"
        elif not dj_first_candidate:
            status = "non_dj_avatar_scope_review_required_report_only"
        else:
            status = "dj_avatar_hash_addressable_binding_required_report_only"

        recovery_row = {
            "avatar_id_hash": stable_hash(row.get("avatar_id")),
            "eid_hash": stable_hash(eid),
            "entity_name_hash": stable_hash(row.get("entity_name")),
            "entity_kind": entity_kind,
            "entity_type": entity_type,
            "platform": str(row.get("platform") or ""),
            "avatar_url_sha256_16": short_hash(url_hash),
            "local_file_sha256_16": short_hash(local_hash),
            "file_size_bytes": file_size,
            "hash_addressable": hash_addressable,
            "dj_first_candidate": dj_first_candidate,
            "serving_dj_id_bound": False,
            "storage_contract_ready": False,
            "public_serving_field_allowed": False,
            "accepted_for_graph": False,
            "write_execution_allowed_now": False,
            "recovery_status": status,
            "blockers": sorted(set(blockers)),
        }
        recovery_rows.append(recovery_row)
        if recovery_row["blockers"]:
            blocked_rows.append(recovery_row)
    return recovery_rows, blocked_rows


def build_media_rollups(rollups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    media_rows: list[dict[str, Any]] = []
    for row in rollups:
        media_count = sum(
            int(row.get(key) or 0)
            for key in ["avatar_count", "yt_channel_count", "sc_stat_count", "mixtape_count"]
        )
        if media_count <= 0:
            continue
        media_rows.append(
            {
                "eid_hash": stable_hash(row.get("eid")),
                "entity_name_hash": stable_hash(row.get("entity_name")),
                "entity_kind": str(row.get("entity_kind") or ""),
                "entity_type": str(row.get("entity_type") or ""),
                "platform_count": len(row.get("platforms") or []),
                "avatar_count": int(row.get("avatar_count") or 0),
                "yt_channel_count": int(row.get("yt_channel_count") or 0),
                "sc_stat_count": int(row.get("sc_stat_count") or 0),
                "mixtape_count": int(row.get("mixtape_count") or 0),
                "media_signal_count": media_count,
                "dj_first_candidate": row.get("entity_kind") == "dj" and row.get("entity_type") == "person",
                "public_serving_field_allowed": False,
                "write_execution_allowed_now": False,
                "recovery_status": "media_signal_rollup_report_only_binding_required",
            }
        )
    return media_rows


def build_work_orders(summary_counts: dict[str, int]) -> list[dict[str, Any]]:
    base = {
        "accepted_for_graph": False,
        "source_raw_db_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_execution_allowed_now": False,
    }
    return [
        {
            **base,
            "work_order_id": "T6_avatar_hash_addressable_storage_contract",
            "priority": 0,
            "input_rows": summary_counts["hash_addressable_avatar_rows"],
            "target_rows": summary_counts["hash_addressable_avatar_rows"],
            "next_gate": "bind report-local avatar hashes to an explicit storage/display contract with checksum readback",
            "status": "ready_for_storage_contract_report_only",
        },
        {
            **base,
            "work_order_id": "T6_dj_avatar_entity_binding_review",
            "priority": 1,
            "input_rows": summary_counts["dj_first_avatar_rows"],
            "target_rows": summary_counts["dj_first_avatar_rows"],
            "next_gate": "prove eid_hash to Atlas dj_id mapping before source/raw or serving avatar fields",
            "status": "serving_identity_binding_required",
        },
        {
            **base,
            "work_order_id": "T6_non_dj_avatar_scope_review",
            "priority": 2,
            "input_rows": summary_counts["non_dj_avatar_rows"],
            "target_rows": summary_counts["non_dj_avatar_rows"],
            "next_gate": "route venue/label/event avatars to non-DJ entity media policy or exclude from DJ profile avatar display",
            "status": "non_dj_scope_review_required",
        },
        {
            **base,
            "work_order_id": "T6_missing_rollup_avatar_review",
            "priority": 3,
            "input_rows": summary_counts["entity_rollup_missing_avatar_rows"],
            "target_rows": summary_counts["entity_rollup_missing_avatar_rows"],
            "next_gate": "recover missing entity rollup or quarantine avatar rows",
            "status": "entity_rollup_recovery_required",
        },
        {
            **base,
            "work_order_id": "T5_avatar_public_serving_field_gate",
            "priority": 4,
            "input_rows": summary_counts["dj_first_avatar_rows"],
            "target_rows": 0,
            "next_gate": "public serving field stays closed until storage contract plus serving readback plus explicit public gate",
            "status": "blocked_public_display_gate_closed",
        },
    ]


def build_packet(
    manifest_dir: Path,
    rendered_ui_contract: Path,
    old_validation_summary: Path,
    completion_rollup_summary: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    reject_unbounded_d_root(manifest_dir, "manifest_dir")
    manifest = read_json(manifest_dir / "manifest.json", "manifest")
    avatar_rows = read_jsonl(manifest_dir / "avatar_artifacts_manifest.jsonl", "avatar_artifacts_manifest")
    entity_rollups = read_jsonl(manifest_dir / "entity_rollups.jsonl", "entity_rollups")
    candidate_rows = read_jsonl(manifest_dir / "candidate_evidence.jsonl", "candidate_evidence")
    rendered_contract = read_json(rendered_ui_contract, "rendered_ui_contract")
    old_summary = read_json(old_validation_summary, "old_validation_summary")
    completion_summary = read_json(completion_rollup_summary, "completion_rollup_summary")

    rollups_by_eid = {str(row.get("eid") or ""): row for row in entity_rollups if row.get("eid")}
    avatar_recovery_rows, avatar_blocked_rows = build_avatar_rows(avatar_rows, rollups_by_eid)
    media_rollup_rows = build_media_rollups(entity_rollups)

    platform_counts = Counter(str(row.get("platform") or "") for row in avatar_rows)
    status_counts = Counter(str(row.get("recovery_status") or "") for row in avatar_recovery_rows)
    blocker_counts = Counter(blocker for row in avatar_recovery_rows for blocker in row.get("blockers", []))
    entity_scope_counts = Counter(f"{row.get('entity_kind')}:{row.get('entity_type')}" for row in avatar_recovery_rows)
    candidate_entity_kind_counts = Counter(str(row.get("entity_kind") or "") for row in candidate_rows)
    media_entity_kind_counts = Counter(str(row.get("entity_kind") or "") for row in media_rollup_rows)

    input_payload_leak_scan = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}
    for payload in [avatar_rows, entity_rollups, candidate_rows]:
        add_leak_counts(input_payload_leak_scan, payload)
    output_payloads = [avatar_recovery_rows, avatar_blocked_rows, media_rollup_rows]
    leak_scan = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}
    for payload in output_payloads:
        add_leak_counts(leak_scan, payload)
    input_leak_scan = manifest.get("leak_scan") or {}

    failed_checks: list[str] = []
    if manifest.get("schema_version") != INPUT_SCHEMA_VERSION:
        failed_checks.append("input_manifest_schema_version_mismatch")
    if int(manifest.get("avatar_artifact_count") or -1) != len(avatar_rows):
        failed_checks.append("manifest_avatar_artifact_count_mismatch")
    if int(manifest.get("input_entity_count") or -1) != len(entity_rollups):
        failed_checks.append("manifest_input_entity_count_mismatch")
    if int(manifest.get("candidate_count") or -1) != len(candidate_rows):
        failed_checks.append("manifest_candidate_count_mismatch")
    if any(int(input_leak_scan.get(key) or 0) for key in ["public_url_hits", "sensitive_key_hits", "local_path_hits"]):
        failed_checks.append("input_manifest_leak_scan_hits")
    if any(input_payload_leak_scan.values()):
        failed_checks.append("input_payload_leak_scan_hits")
    if any(leak_scan.values()):
        failed_checks.append("output_payload_leak_scan_hits")
    if not avatar_rows:
        failed_checks.append("avatar_artifact_rows_missing")

    counts = {
        "input_candidate_rows": len(candidate_rows),
        "input_entity_rollup_rows": len(entity_rollups),
        "input_avatar_artifact_rows": len(avatar_rows),
        "old_validation_avatar_rows": int((old_summary.get("counts") or {}).get("actual_avatar_artifact_rows") or 0),
        "old_validation_avatar_hash_ready_rows": int((old_summary.get("counts") or {}).get("avatar_hash_ready_rows") or 0),
        "old_validation_avatar_blocked_rows": int((old_summary.get("counts") or {}).get("avatar_blocked_rows") or 0),
        "hash_addressable_avatar_rows": sum(1 for row in avatar_recovery_rows if row["hash_addressable"]),
        "dj_first_avatar_rows": sum(1 for row in avatar_recovery_rows if row["dj_first_candidate"]),
        "non_dj_avatar_rows": sum(1 for row in avatar_recovery_rows if row["entity_kind"] not in {"dj", "missing_rollup"}),
        "entity_rollup_missing_avatar_rows": sum(1 for row in avatar_recovery_rows if row["entity_kind"] == "missing_rollup"),
        "binary_or_storage_contract_blocked_rows": sum(1 for row in avatar_recovery_rows if row["recovery_status"] == "binary_or_storage_contract_blocked_report_only"),
        "serving_dj_id_bound_rows": 0,
        "storage_contract_ready_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "accepted_for_graph_rows": 0,
        "source_raw_db_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
        "media_signal_rollup_rows": len(media_rollup_rows),
        "dj_media_signal_rollup_rows": sum(1 for row in media_rollup_rows if row["dj_first_candidate"]),
        "rendered_ui_public_serving_field_rows": int((rendered_contract.get("counts") or {}).get("public_serving_field_rows") or 0),
        "completion_dj_profile_avatar_missing": int((completion_summary.get("quality_gap_counts") or {}).get("dj_profile_avatar_missing") or 0),
        "completion_dj_profile_media_missing": int((completion_summary.get("quality_gap_counts") or {}).get("dj_profile_media_missing") or 0),
    }
    work_orders = build_work_orders(counts)
    decision = "atlas_t6_avatar_media_recovery_ready_report_only" if not failed_checks else "atlas_t6_avatar_media_recovery_blocked_report_only"
    generated_at = now_iso()
    contract = {
        "schema_version": f"{SCHEMA_VERSION}.contract",
        "generated_at": generated_at,
        "decision": decision,
        "report_only": True,
        "deployable_public": False,
        "source_manifest_run_id": manifest.get("run_id"),
        "v4_manifest_replaces_old_avatar_validation_counts": counts["input_avatar_artifact_rows"] > counts["old_validation_avatar_rows"],
        "avatar_merge_policy": {
            "hash_addressable_rows_can_enter_storage_contract": counts["hash_addressable_avatar_rows"],
            "dj_first_rows_require_eid_to_atlas_dj_id_binding": counts["dj_first_avatar_rows"],
            "non_dj_rows_require_entity_media_scope_review": counts["non_dj_avatar_rows"],
            "public_display_fields_stay_closed": True,
        },
        "prewrite_requirements": [
            "bind each eid_hash to an explicit Atlas entity id and block ambiguous joins",
            "materialize avatar storage refs from hash-addressable artifacts without exposing raw URLs or local paths",
            "read back storage checksum/size before any serving field mutation",
            "separate DJ profile avatars from venue/label/event media",
            "keep huaidj.club upload disabled until the user explicitly re-enables public promotion",
        ],
        "postwrite_requirements": [
            "read back avatar/media rows by deterministic entity selector and local_file_sha256_16",
            "rebuild a local serving candidate and verify avatar/media coverage deltas",
            "run local UI/API smoke before any public serving field promotion",
            "produce rollback evidence for every inserted or updated storage/display row",
        ],
        "write_guards": WRITE_GUARDS,
        "next_resume_pointer": display_path(out_dir / "avatar_media_recovery_work_orders.jsonl"),
    }
    summary = {
        "schema_version": f"{SCHEMA_VERSION}.summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": sorted(set(failed_checks)),
        "counts": counts,
        "platform_counts_top": top_counts(platform_counts),
        "entity_scope_counts_top": top_counts(entity_scope_counts),
        "recovery_status_counts_top": top_counts(status_counts),
        "blockers_top": top_counts(blocker_counts),
        "candidate_entity_kind_counts_top": top_counts(candidate_entity_kind_counts),
        "media_entity_kind_counts_top": top_counts(media_entity_kind_counts),
        "leak_scan": leak_scan,
        "input_manifest_leak_scan": {
            "public_url_hits": int(input_leak_scan.get("public_url_hits") or 0),
            "sensitive_key_hits": int(input_leak_scan.get("sensitive_key_hits") or 0),
            "local_path_hits": int(input_leak_scan.get("local_path_hits") or 0),
        },
        "input_payload_leak_scan": input_payload_leak_scan,
        "inputs": {
            "manifest_dir": display_path(manifest_dir),
            "rendered_ui_contract": display_path(rendered_ui_contract),
            "old_validation_summary": display_path(old_validation_summary),
            "completion_rollup_summary": display_path(completion_rollup_summary),
        },
        "outputs": {
            "contract": display_path(out_dir / "avatar_media_recovery_contract.json"),
            "avatar_recovery_rows": display_path(out_dir / "avatar_recovery_rows.jsonl"),
            "media_recovery_rollups": display_path(out_dir / "media_recovery_rollups.jsonl"),
            "avatar_media_blocked_rows": display_path(out_dir / "avatar_media_blocked_rows.jsonl"),
            "avatar_media_recovery_work_orders": display_path(out_dir / "avatar_media_recovery_work_orders.jsonl"),
            "summary_json": display_path(out_dir / "avatar_media_recovery_summary.json"),
            "summary_md": display_path(out_dir / "avatar_media_recovery_summary.md"),
            "report": display_path(report_path),
        },
        "write_guards": WRITE_GUARDS,
        "next_resume_pointer": display_path(out_dir / "avatar_media_recovery_work_orders.jsonl"),
        "stop_reason": "avatar_media_recovery_v4_ready_report_only_storage_and_identity_binding_required"
        if not failed_checks
        else "avatar_media_recovery_v4_blocked",
        "wait_reason": "Need storage/display contract and eid-to-Atlas-entity binding before DB/serving/public writes.",
    }

    write_json(out_dir / "avatar_media_recovery_contract.json", contract)
    write_jsonl(out_dir / "avatar_recovery_rows.jsonl", avatar_recovery_rows)
    write_jsonl(out_dir / "media_recovery_rollups.jsonl", media_rollup_rows)
    write_jsonl(out_dir / "avatar_media_blocked_rows.jsonl", avatar_blocked_rows)
    write_jsonl(out_dir / "avatar_media_recovery_work_orders.jsonl", work_orders)
    write_json(out_dir / "leak_scan.json", leak_scan)
    write_json(out_dir / "avatar_media_recovery_summary.json", summary)
    write_text(out_dir / "avatar_media_recovery_summary.md", render_report(summary))
    write_text(report_path, render_report(summary))
    return summary


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    leak = summary["leak_scan"]
    input_leak = summary["input_manifest_leak_scan"]
    input_payload_leak = summary["input_payload_leak_scan"]
    return "\n".join(
        [
            "# Atlas T6 Avatar/Media Recovery Packet - 2026-05-27",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            "- LLM audit finding: the older avatar validation gate only covered 2 avatar rows, while the later v4 WSL2 sidecar manifest contains 68 hash-addressable avatar artifacts. Treat the old 2-row avatar conclusion as stale for avatar/media planning and use this v4 packet for the next storage/entity-binding contract.",
            "",
            "## Evidence",
            "",
            f"- Inputs: `{summary['inputs']}`",
            f"- Outputs: `{summary['outputs']}`",
            f"- v4 candidates/entity-rollups/avatar rows: `{counts['input_candidate_rows']}/{counts['input_entity_rollup_rows']}/{counts['input_avatar_artifact_rows']}`",
            f"- Old validation avatar actual/hash-ready/blocked rows: `{counts['old_validation_avatar_rows']}/{counts['old_validation_avatar_hash_ready_rows']}/{counts['old_validation_avatar_blocked_rows']}`",
            f"- Hash-addressable / DJ-first / non-DJ / missing-rollup avatar rows: `{counts['hash_addressable_avatar_rows']}/{counts['dj_first_avatar_rows']}/{counts['non_dj_avatar_rows']}/{counts['entity_rollup_missing_avatar_rows']}`",
            f"- Storage-ready / public-serving-field / accepted-for-graph rows: `{counts['storage_contract_ready_rows']}/{counts['public_serving_field_allowed_rows']}/{counts['accepted_for_graph_rows']}`",
            f"- Media signal rollups total/DJ-first: `{counts['media_signal_rollup_rows']}/{counts['dj_media_signal_rollup_rows']}`",
            f"- Completion rollup DJ avatar/media missing rows: `{counts['completion_dj_profile_avatar_missing']}/{counts['completion_dj_profile_media_missing']}`",
            f"- Platform counts top: `{summary['platform_counts_top']}`",
            f"- Entity scope counts top: `{summary['entity_scope_counts_top']}`",
            f"- Recovery status counts top: `{summary['recovery_status_counts_top']}`",
            f"- Blockers top: `{summary['blockers_top']}`",
            f"- Input manifest leak scan public_url/sensitive_key/local_path: `{input_leak['public_url_hits']}/{input_leak['sensitive_key_hits']}/{input_leak['local_path_hits']}`",
            f"- Input payload leak scan public_url/sensitive_key/local_path: `{input_payload_leak['public_url_hits']}/{input_payload_leak['sensitive_key_hits']}/{input_payload_leak['local_path_hits']}`",
            f"- Output leak scan public_url/sensitive_key/local_path: `{leak['public_url_hits']}/{leak['sensitive_key_hits']}/{leak['local_path_hits']}`",
            "",
            "## Boundary",
            "",
            "- This is a report-only avatar/media recovery contract packet.",
            "- It reads only repo-local hash/redacted manifest artifacts and report-local contracts.",
            "- It does not read WSL scratch raw SQLite, raw source URLs, cookies, browser stores, secrets, or .env files.",
            "- It does not fetch network, download avatars, run OCR/model calls, open or write source/raw Atlas DB, write/rebuild serving SQLite, write Neo4j/Qdrant/production SQLite, update public pointer, upload huaidj.club, upload/review mini-program, write memory, use 9router, run destructive Git, or scan D: roots.",
            "- huaidj.club/public upload remains disabled until explicitly re-enabled.",
            "",
            "## Next Resume Pointer",
            "",
            f"`{summary['next_resume_pointer']}`",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--rendered-ui-contract", type=Path, default=DEFAULT_RENDERED_UI_CONTRACT)
    parser.add_argument("--old-validation-summary", type=Path, default=DEFAULT_OLD_VALIDATION_SUMMARY)
    parser.add_argument("--completion-rollup-summary", type=Path, default=DEFAULT_COMPLETION_ROLLUP_SUMMARY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(
        args.manifest_dir,
        args.rendered_ui_contract,
        args.old_validation_summary,
        args.completion_rollup_summary,
        args.out_dir,
        args.report,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "failed_checks": summary["failed_checks"],
                "summary": str(args.out_dir / "avatar_media_recovery_summary.json"),
                "next_resume_pointer": summary["next_resume_pointer"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
