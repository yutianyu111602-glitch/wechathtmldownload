#!/usr/bin/env python3
"""Validate the redacted T6 sidecar manifest before Atlas DB merge gates.

This report-only gate consumes the sanitized outlink/avatar manifest produced
from the WSL2 sidecar and the selected Atlas serving SQLite in read-only mode.
It verifies count integrity, entity coverage, write guards, duplicate drift,
and redaction before any source/raw DB, serving, graph, vector, or public-state
mutation is allowed.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_MANIFEST_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_redacted_manifest_20260526"
DEFAULT_SERVING_DB = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "atlas_serving.sqlite"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_manifest_validation_gate_t5_t6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_T6_SIDECAR_MANIFEST_VALIDATION_GATE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_t6_sidecar_manifest_validation_gate.v1"
INPUT_SCHEMA_VERSION = "stage7_atlas_t6_sidecar_redacted_manifest.v1"

URL_RE = re.compile(r"https?://|www\.", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization|bearer|pass_ticket|openid)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)

EXPECTED_WRITE_GUARDS = {
    "report_only": True,
    "source_raw_db_write_executed": False,
    "serving_sqlite_write_executed": False,
    "serving_rebuild_executed": False,
    "neo4j_write_executed": False,
    "qdrant_write_executed": False,
    "public_pointer_updated": False,
    "huaidj_club_upload_executed": False,
    "memory_write_executed": False,
}

REQUIRED_CANDIDATE_FIELDS = {
    "candidate_id",
    "candidate_kind",
    "canonical_url_key",
    "entity_id",
    "host",
    "platform",
    "url_redacted",
    "url_sha256",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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
                raise ValueError(f"{path}:{line_no}: expected object row")
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


def connect_readonly(path: Path) -> sqlite3.Connection:
    reject_unbounded_d_root(path, "serving_db")
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?", (table,)).fetchone() is not None


def load_serving_profiles(serving_db: Path) -> dict[str, dict[str, Any]]:
    conn = connect_readonly(serving_db)
    try:
        if not table_exists(conn, "dj_profile"):
            raise ValueError(f"serving db has no dj_profile table: {serving_db}")
        profiles: dict[str, dict[str, Any]] = {}
        for row in conn.execute("SELECT dj_id, display_name, normalized_name, city_primary, event_count, collaborator_count, media_count FROM dj_profile"):
            profiles[str(row["dj_id"])] = {
                "dj_id": row["dj_id"],
                "display_name": row["display_name"],
                "normalized_name": row["normalized_name"],
                "city_primary": row["city_primary"],
                "event_count": row["event_count"],
                "collaborator_count": row["collaborator_count"],
                "media_count": row["media_count"],
            }
        return profiles
    finally:
        conn.close()


def leak_counts_for(payload: Any) -> dict[str, int]:
    counts = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}

    def visit(value: Any, key: str = "") -> None:
        if SECRET_RE.search(key):
            counts["sensitive_key_hits"] += 1
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(child_value, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str):
            counts["public_url_hits"] += len(URL_RE.findall(value))
            counts["sensitive_key_hits"] += len(SECRET_RE.findall(value))
            counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(value))

    visit(payload)
    return counts


def add_leak_counts(total: dict[str, int], payload: Any) -> None:
    hits = leak_counts_for(payload)
    for key, value in hits.items():
        total[key] += value


def all_write_guards_closed(guards: dict[str, Any]) -> bool:
    return all(guards.get(key) is expected for key, expected in EXPECTED_WRITE_GUARDS.items())


def top_counts(counter: Counter[str], limit: int = 20) -> dict[str, int]:
    return {key: value for key, value in counter.most_common(limit)}


def validation_status(blockers: list[str], row: dict[str, Any]) -> str:
    if blockers:
        if row.get("candidate_kind") == "identity_candidate" or row.get("blocked_reason"):
            return "review_required_report_only"
        return "blocked_report_only"
    return "merge_precheck_ready_report_only"


def row_has_leak(row: dict[str, Any]) -> bool:
    return any(leak_counts_for(row).values())


def validate_candidate_rows(candidates: list[dict[str, Any]], serving_profiles: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    candidate_id_counts = Counter(str(row.get("candidate_id") or "") for row in candidates)
    url_key_counts = Counter(str(row.get("canonical_url_key") or "") for row in candidates)
    serving_ids = set(serving_profiles)
    validation_rows: list[dict[str, Any]] = []
    merge_ready_rows: list[dict[str, Any]] = []
    review_required_rows: list[dict[str, Any]] = []

    for row in candidates:
        blockers: list[str] = []
        missing = sorted(field for field in REQUIRED_CANDIDATE_FIELDS if not row.get(field))
        blockers.extend(f"missing_{field}" for field in missing)
        candidate_id = str(row.get("candidate_id") or "")
        canonical_url_key = str(row.get("canonical_url_key") or "")
        entity_id = str(row.get("entity_id") or "")
        if candidate_id and candidate_id_counts[candidate_id] > 1:
            blockers.append("duplicate_candidate_id")
        if canonical_url_key and url_key_counts[canonical_url_key] > 1:
            blockers.append("duplicate_canonical_url_key")
        if entity_id and entity_id not in serving_ids:
            blockers.append("missing_serving_entity")
        if row.get("accepted_for_graph") is not False:
            blockers.append("accepted_for_graph_not_false")
        if row.get("public_serving_field_allowed") is not False:
            blockers.append("public_serving_field_allowed_not_false")
        if row.get("candidate_kind") not in {"profile", "outlink", "identity_candidate"}:
            blockers.append("unsupported_candidate_kind")
        if row_has_leak(row):
            blockers.append("redaction_leak_in_candidate_row")
        if row.get("candidate_kind") == "identity_candidate" or row.get("blocked_reason"):
            blockers.append(str(row.get("blocked_reason") or "identity_candidate_requires_source_context_review"))

        status = validation_status(sorted(set(blockers)), row)
        validation_row = {
            "candidate_id": candidate_id,
            "candidate_kind": row.get("candidate_kind", ""),
            "entity_id": entity_id,
            "host": row.get("host", ""),
            "platform": row.get("platform", ""),
            "canonical_url_key": canonical_url_key,
            "validation_status": status,
            "validation_blockers": sorted(set(blockers)),
            "accepted_for_graph": False,
            "source_raw_db_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
            "write_execution_allowed_now": False,
            "required_next_evidence": "explicit source/raw target DB provenance, prewrite snapshot, inverse rollback, minimal write scope, and postwrite readback",
        }
        validation_rows.append(validation_row)
        if status == "merge_precheck_ready_report_only":
            merge_ready_rows.append(validation_row)
        elif status == "review_required_report_only":
            review_required_rows.append(validation_row)
    return validation_rows, merge_ready_rows, review_required_rows


def validate_entity_rollups(entity_rollups: list[dict[str, Any]], candidates: list[dict[str, Any]], serving_profiles: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter[str]]:
    candidates_by_entity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        if row.get("entity_id"):
            candidates_by_entity[str(row["entity_id"])].append(row)
    serving_ids = set(serving_profiles)
    mismatch_reasons: Counter[str] = Counter()
    validation_rows: list[dict[str, Any]] = []
    for rollup in entity_rollups:
        entity_id = str(rollup.get("entity_id") or "")
        blockers: list[str] = []
        if not entity_id:
            blockers.append("missing_entity_id")
        if entity_id and entity_id not in serving_ids:
            blockers.append("missing_serving_entity")
        observed_counts = Counter(str(row.get("candidate_kind") or "") for row in candidates_by_entity.get(entity_id, []))
        declared_counts = Counter({str(key): int(value) for key, value in dict(rollup.get("candidate_counts_by_kind") or {}).items()})
        if observed_counts != declared_counts:
            blockers.append("entity_candidate_counts_mismatch")
        if row_has_leak(rollup):
            blockers.append("redaction_leak_in_entity_rollup")
        for blocker in blockers:
            mismatch_reasons[blocker] += 1
        validation_rows.append(
            {
                "entity_id": entity_id,
                "candidate_rows": sum(observed_counts.values()),
                "declared_candidate_counts_by_kind": dict(declared_counts),
                "observed_candidate_counts_by_kind": dict(observed_counts),
                "serving_entity_present": entity_id in serving_ids,
                "merge_status": rollup.get("merge_status", ""),
                "validation_blockers": sorted(set(blockers)),
                "source_raw_db_write_allowed": False,
                "write_execution_allowed_now": False,
            }
        )
    return validation_rows, mismatch_reasons


def validate_avatar_rows(avatar_rows: list[dict[str, Any]], serving_profiles: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    serving_ids = set(serving_profiles)
    validation_rows: list[dict[str, Any]] = []
    for row in avatar_rows:
        blockers: list[str] = []
        entity_id = str(row.get("entity_id") or "")
        if entity_id and entity_id not in serving_ids:
            blockers.append("missing_serving_entity")
        if not entity_id:
            blockers.append("missing_entity_id")
        if not row.get("content_sha256"):
            blockers.append(str(row.get("blocked_reason") or "missing_avatar_content_hash"))
        if row.get("blocked_reason"):
            blockers.append(str(row.get("blocked_reason")))
        if row_has_leak(row):
            blockers.append("redaction_leak_in_avatar_row")
        validation_rows.append(
            {
                "avatar_asset_id": row.get("avatar_asset_id", ""),
                "candidate_id": row.get("candidate_id", ""),
                "entity_id": entity_id,
                "download_status": row.get("download_status", ""),
                "content_hash_ready": bool(row.get("content_sha256")) and not row.get("blocked_reason"),
                "validation_blockers": sorted(set(blockers)),
                "source_raw_db_write_allowed": False,
                "public_serving_field_allowed": False,
                "write_execution_allowed_now": False,
            }
        )
    return validation_rows


def build_packet(manifest_dir: Path, serving_db: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    reject_unbounded_d_root(manifest_dir, "manifest_dir")
    manifest = read_json(manifest_dir / "manifest.json", "manifest")
    candidates = read_jsonl(manifest_dir / "candidate_evidence.jsonl", "candidate_evidence")
    entity_rollups = read_jsonl(manifest_dir / "entity_rollups.jsonl", "entity_rollups")
    avatar_rows = read_jsonl(manifest_dir / "avatar_artifacts_manifest.jsonl", "avatar_artifacts")
    upstream_blocked_rows = read_jsonl(manifest_dir / "blocked_rows.jsonl", "blocked_rows")
    serving_profiles = load_serving_profiles(serving_db)

    candidate_validation_rows, merge_ready_rows, review_required_rows = validate_candidate_rows(candidates, serving_profiles)
    entity_validation_rows, entity_mismatch_reasons = validate_entity_rollups(entity_rollups, candidates, serving_profiles)
    avatar_validation_rows = validate_avatar_rows(avatar_rows, serving_profiles)

    candidate_blockers = Counter(
        blocker
        for row in candidate_validation_rows
        for blocker in row["validation_blockers"]
        if row["validation_status"] != "review_required_report_only" or blocker not in {"source_context_not_verified_identity_review_only", "identity_candidate_requires_source_context_review"}
    )
    review_reasons = Counter(
        blocker
        for row in candidate_validation_rows
        for blocker in row["validation_blockers"]
        if row["validation_status"] == "review_required_report_only"
    )
    avatar_blockers = Counter(blocker for row in avatar_validation_rows for blocker in row["validation_blockers"])
    upstream_blockers = Counter(str(row.get("blocked_reason") or "unknown") for row in upstream_blocked_rows)
    duplicate_candidate_id_groups = sum(1 for _, count in Counter(row.get("candidate_id") for row in candidates).items() if count > 1)
    duplicate_url_key_groups = sum(1 for _, count in Counter(row.get("canonical_url_key") for row in candidates).items() if count > 1)
    missing_serving_entity_refs = sum(1 for row in candidate_validation_rows if "missing_serving_entity" in row["validation_blockers"])

    leak_scan = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}
    add_leak_counts(leak_scan, manifest)
    add_leak_counts(leak_scan, candidates)
    add_leak_counts(leak_scan, entity_rollups)
    add_leak_counts(leak_scan, avatar_rows)
    add_leak_counts(leak_scan, candidate_validation_rows)
    add_leak_counts(leak_scan, entity_validation_rows)
    add_leak_counts(leak_scan, avatar_validation_rows)
    add_leak_counts(leak_scan, upstream_blocked_rows)

    failed_checks: list[str] = []
    if manifest.get("schema_version") != INPUT_SCHEMA_VERSION:
        failed_checks.append("input_manifest_schema_version_mismatch")
    count_expectations = {
        "candidate_count": len(candidates),
        "input_entity_count": len(entity_rollups),
        "avatar_artifact_count": len(avatar_rows),
        "blocked_count": len(upstream_blocked_rows),
    }
    for manifest_key, actual in count_expectations.items():
        if int(manifest.get(manifest_key) or -1) != actual:
            failed_checks.append(f"manifest_{manifest_key}_mismatch")
    manifest_leak = manifest.get("leak_scan") or {}
    if any(int(manifest_leak.get(key) or 0) for key in ["public_url_hits", "sensitive_key_hits", "local_path_hits"]):
        failed_checks.append("input_manifest_leak_scan_hits")
    if any(leak_scan.values()):
        failed_checks.append("validation_payload_leak_scan_hits")
    if not all_write_guards_closed(dict(manifest.get("write_guards") or {})):
        failed_checks.append("input_manifest_write_guards_not_closed")
    if duplicate_candidate_id_groups:
        failed_checks.append("duplicate_candidate_id_groups_present")
    if duplicate_url_key_groups:
        failed_checks.append("duplicate_canonical_url_key_groups_present")
    if missing_serving_entity_refs:
        failed_checks.append("missing_serving_entity_refs_present")
    if entity_mismatch_reasons:
        failed_checks.append("entity_rollup_validation_blockers_present")
    hard_candidate_blockers = {
        key: value
        for key, value in candidate_blockers.items()
        if key
        and key
        not in {
            "source_context_not_verified_identity_review_only",
            "identity_candidate_requires_source_context_review",
        }
    }
    if hard_candidate_blockers:
        failed_checks.append("candidate_validation_blockers_present")

    counts = {
        "input_manifest_candidate_count": int(manifest.get("candidate_count") or 0),
        "actual_candidate_rows": len(candidates),
        "actual_entity_rollups": len(entity_rollups),
        "actual_avatar_artifact_rows": len(avatar_rows),
        "actual_upstream_blocked_rows": len(upstream_blocked_rows),
        "serving_profile_rows": len(serving_profiles),
        "unique_candidate_entity_ids": len({row.get("entity_id") for row in candidates if row.get("entity_id")}),
        "merge_precheck_ready_rows": len(merge_ready_rows),
        "review_required_rows": len(review_required_rows),
        "validation_blocked_candidate_rows": sum(1 for row in candidate_validation_rows if row["validation_status"] == "blocked_report_only"),
        "identity_review_required_rows": sum(1 for row in candidate_validation_rows if row["candidate_kind"] == "identity_candidate"),
        "duplicate_candidate_id_groups": duplicate_candidate_id_groups,
        "duplicate_canonical_url_key_groups": duplicate_url_key_groups,
        "missing_serving_entity_refs": missing_serving_entity_refs,
        "entity_rollup_validation_blocked_rows": sum(1 for row in entity_validation_rows if row["validation_blockers"]),
        "avatar_hash_ready_rows": sum(1 for row in avatar_validation_rows if row["content_hash_ready"]),
        "avatar_blocked_rows": sum(1 for row in avatar_validation_rows if row["validation_blockers"]),
        "source_raw_db_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
    }
    decision = "atlas_t6_sidecar_manifest_validation_gate_ready_report_only" if not failed_checks else "atlas_t6_sidecar_manifest_validation_gate_blocked_report_only"
    generated_at = now_iso()
    write_guards = {
        "report_only": True,
        "write_execution_allowed_now": False,
        "source_raw_db_write_allowed": False,
        "source_raw_db_write_executed": False,
        "serving_sqlite_write_executed": False,
        "serving_rebuild_executed": False,
        "neo4j_write_executed": False,
        "qdrant_write_executed": False,
        "public_pointer_updated": False,
        "huaidj_club_upload_executed": False,
        "memory_write_executed": False,
    }
    merge_contract = {
        "schema_version": f"{SCHEMA_VERSION}.merge_contract",
        "generated_at": generated_at,
        "decision": decision,
        "write_execution_allowed_now": False,
        "source_raw_db_target_required": True,
        "huaidj_club_upload_allowed_now": False,
        "candidate_scope": {
            "merge_precheck_ready_rows": len(merge_ready_rows),
            "review_required_rows": len(review_required_rows),
            "avatar_hash_ready_rows": counts["avatar_hash_ready_rows"],
            "avatar_blocked_rows": counts["avatar_blocked_rows"],
            "upstream_blocked_rows": len(upstream_blocked_rows),
        },
        "prewrite_requirements": [
            "bind an explicit source/raw Atlas target DB path from trusted repo-local evidence",
            "open target DB read-only and prove schema/table compatibility",
            "materialize prewrite row snapshots for every selected entity/link selector",
            "materialize inverse rollback rows before any mutation",
            "dedupe by entity_id plus canonical_url_key plus platform and block drift",
            "keep identity_candidate rows closed until source-context review supplies stronger evidence",
            "keep avatar rows closed until content_sha256 and storage contract are ready",
        ],
        "postwrite_readback_requirements": [
            "read back inserted/updated link rows by deterministic selectors",
            "verify row hashes and rollback invertibility",
            "rebuild selected serving candidate and prove DJ/entity/link counts",
            "run graph/search/API smoke against the rebuilt local candidate",
            "keep public upload disabled until the user re-enables huaidj.club promotion",
        ],
        "write_guards": write_guards,
    }
    validation_blockers = [
        {"blocker": key, "count": value, "blocker_source": "candidate_validation"} for key, value in sorted(candidate_blockers.items())
    ] + [
        {"blocker": key, "count": value, "blocker_source": "review_required"} for key, value in sorted(review_reasons.items())
    ] + [
        {"blocker": key, "count": value, "blocker_source": "entity_rollup_validation"} for key, value in sorted(entity_mismatch_reasons.items())
    ] + [
        {"blocker": key, "count": value, "blocker_source": "avatar_validation"} for key, value in sorted(avatar_blockers.items())
    ] + [
        {"blocker": key, "count": value, "blocker_source": "upstream_blocked_manifest_rows"} for key, value in sorted(upstream_blockers.items())
    ]
    summary = {
        "schema_version": f"{SCHEMA_VERSION}.summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": sorted(set(failed_checks)),
        "counts": counts,
        "leak_scan": leak_scan,
        "candidate_validation_blockers_top": top_counts(candidate_blockers),
        "review_required_reasons_top": top_counts(review_reasons),
        "avatar_blockers_top": top_counts(avatar_blockers),
        "upstream_blocked_reasons_top": top_counts(upstream_blockers),
        "inputs": {
            "manifest_dir": display_path(manifest_dir),
            "serving_db_basename": serving_db.name,
        },
        "outputs": {
            "merge_contract": display_path(out_dir / "merge_contract.json"),
            "candidate_validation_rows": display_path(out_dir / "candidate_validation_rows.jsonl"),
            "merge_precheck_ready_candidates": display_path(out_dir / "merge_precheck_ready_candidates.jsonl"),
            "merge_review_required_candidates": display_path(out_dir / "merge_review_required_candidates.jsonl"),
            "entity_validation_rollups": display_path(out_dir / "entity_validation_rollups.jsonl"),
            "avatar_validation_rows": display_path(out_dir / "avatar_validation_rows.jsonl"),
            "validation_blockers": display_path(out_dir / "validation_blockers.jsonl"),
            "summary_json": display_path(out_dir / "sidecar_manifest_validation_summary.json"),
            "report": display_path(report_path),
        },
        "write_guards": write_guards,
        "next_resume_pointer": display_path(out_dir / "merge_contract.json"),
        "stop_reason": "report_only_sidecar_manifest_validation_ready_write_gates_still_closed"
        if not failed_checks
        else "report_only_sidecar_manifest_validation_blocked",
        "wait_reason": "Need explicit source/raw target DB binding and prewrite/rollback/postwrite evidence before any Atlas DB merge.",
    }

    write_json(out_dir / "merge_contract.json", merge_contract)
    write_jsonl(out_dir / "candidate_validation_rows.jsonl", candidate_validation_rows)
    write_jsonl(out_dir / "merge_precheck_ready_candidates.jsonl", merge_ready_rows)
    write_jsonl(out_dir / "merge_review_required_candidates.jsonl", review_required_rows)
    write_jsonl(out_dir / "entity_validation_rollups.jsonl", entity_validation_rows)
    write_jsonl(out_dir / "avatar_validation_rows.jsonl", avatar_validation_rows)
    write_jsonl(out_dir / "validation_blockers.jsonl", validation_blockers)
    write_json(out_dir / "leak_scan.json", leak_scan)
    write_json(out_dir / "sidecar_manifest_validation_summary.json", summary)
    write_text(report_path, render_report(summary))
    return summary


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    leak = summary["leak_scan"]
    return "\n".join(
        [
            "# Atlas T5/T6 Sidecar Manifest Validation Gate - 2026-05-26",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            "- LLM audit finding: the WSL2 sidecar output is useful for DJ social/outlink enrichment, but it must remain a hashed/redacted merge contract until source/raw target DB provenance, rollback, and postwrite readback are bound.",
            "",
            "## Evidence",
            "",
            f"- Inputs: `{summary['inputs']}`",
            f"- Outputs: `{summary['outputs']}`",
            f"- Candidates/entity rollups/avatar/upstream-blocked rows: `{counts['actual_candidate_rows']}/{counts['actual_entity_rollups']}/{counts['actual_avatar_artifact_rows']}/{counts['actual_upstream_blocked_rows']}`",
            f"- Serving profile rows: `{counts['serving_profile_rows']}`",
            f"- Merge precheck ready/review-required/blocked candidate rows: `{counts['merge_precheck_ready_rows']}/{counts['review_required_rows']}/{counts['validation_blocked_candidate_rows']}`",
            f"- Identity review required rows: `{counts['identity_review_required_rows']}`",
            f"- Duplicate candidate/url-key groups: `{counts['duplicate_candidate_id_groups']}/{counts['duplicate_canonical_url_key_groups']}`",
            f"- Missing serving entity refs: `{counts['missing_serving_entity_refs']}`",
            f"- Entity rollup validation blocked rows: `{counts['entity_rollup_validation_blocked_rows']}`",
            f"- Avatar hash-ready/blocked rows: `{counts['avatar_hash_ready_rows']}/{counts['avatar_blocked_rows']}`",
            f"- Leak scan public_url/sensitive_key/local_path: `{leak['public_url_hits']}/{leak['sensitive_key_hits']}/{leak['local_path_hits']}`",
            f"- Review-required reasons top: `{summary['review_required_reasons_top']}`",
            f"- Avatar blockers top: `{summary['avatar_blockers_top']}`",
            f"- Upstream blocked reasons top: `{summary['upstream_blocked_reasons_top']}`",
            "",
            "## Boundary",
            "",
            "- This is a report-only validation gate for T5/T6 merge planning.",
            "- It opens only the selected serving SQLite in read-only mode and reads only the redacted manifest artifacts.",
            "- It does not open or write source/raw Atlas DB, write/rebuild serving SQLite, write Neo4j/Qdrant/production SQLite, update public pointers, deploy CloudRun/VPS, upload huaidj.club or mini-program, call network/model APIs, read credentials, write memory, run destructive Git, use 9router, or scan D: roots.",
            "- huaidj.club upload remains disabled until the user explicitly re-enables public promotion.",
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
    parser.add_argument("--serving-db", type=Path, default=DEFAULT_SERVING_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(args.manifest_dir, args.serving_db, args.out_dir, args.report)
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "failed_checks": summary["failed_checks"],
                "summary": str(args.out_dir / "sidecar_manifest_validation_summary.json"),
                "next_resume_pointer": summary["next_resume_pointer"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
