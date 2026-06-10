#!/usr/bin/env python3
"""Build a report-only avatar storage contract gate for Atlas T6 evidence.

The gate consumes the v4 hash/redacted avatar recovery packet and materializes a
deterministic content-addressed storage contract. It does not read binary files,
open SQLite, write storage, rebuild serving, or expose raw URLs/paths.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import build_atlas_t6_avatar_media_recovery_packet as recovery


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_RECOVERY_DIR = STAGE7_ROOT / "reports" / "atlas_t6_avatar_media_recovery_packet_20260527"
DEFAULT_MANIFEST_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_redacted_manifest_20260526_v4"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_avatar_storage_contract_gate_20260527"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_AVATAR_STORAGE_CONTRACT_GATE_20260527.md"
SCHEMA_VERSION = "stage7_atlas_t6_avatar_storage_contract_gate.v1"
WRITE_GUARDS = {
    "report_only": True,
    "write_execution_allowed_now": False,
    "source_raw_db_opened": False,
    "source_raw_db_write_executed": False,
    "serving_sqlite_opened": False,
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


def load_avatar_artifact_index(manifest_dir: Path) -> dict[str, dict[str, Any]]:
    avatar_rows = recovery.read_jsonl(manifest_dir / "avatar_artifacts_manifest.jsonl", "avatar artifacts")
    index: dict[str, dict[str, Any]] = {}
    for row in avatar_rows:
        avatar_id_hash = recovery.stable_hash(row.get("avatar_id"))
        index[avatar_id_hash] = {
            "avatar_id_hash": avatar_id_hash,
            "avatar_url_sha256": row.get("avatar_url_sha256") or "",
            "file_size_bytes": int(row.get("file_size_bytes") or 0),
            "local_file_sha256": row.get("local_file_sha256") or "",
            "platform": row.get("platform") or "unknown",
        }
    return index


def storage_key(local_file_sha256: str) -> str:
    prefix = local_file_sha256[:2]
    return f"atlas-avatar-sha256/{prefix}/{local_file_sha256}"


def build_contract_rows(recovery_rows: list[dict[str, Any]], artifacts_by_avatar_hash: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ready_rows: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []
    for row in recovery_rows:
        artifact = artifacts_by_avatar_hash.get(str(row.get("avatar_id_hash") or ""), {})
        full_hash = str(artifact.get("local_file_sha256") or "")
        url_hash = str(artifact.get("avatar_url_sha256") or "")
        file_size = int(artifact.get("file_size_bytes") or row.get("file_size_bytes") or 0)
        blockers: list[str] = []
        if not recovery.HASH64_RE.match(full_hash):
            blockers.append("full_local_file_sha256_missing")
        if not recovery.HASH64_RE.match(url_hash):
            blockers.append("full_avatar_url_sha256_missing")
        if file_size <= 0:
            blockers.append("file_size_missing")
        base = {
            "accepted_for_graph": False,
            "avatar_id_hash": row.get("avatar_id_hash"),
            "avatar_url_sha256": url_hash if recovery.HASH64_RE.match(url_hash) else "",
            "dj_first_candidate": bool(row.get("dj_first_candidate")),
            "eid_hash": row.get("eid_hash"),
            "entity_kind": row.get("entity_kind"),
            "entity_name_hash": row.get("entity_name_hash"),
            "entity_type": row.get("entity_type"),
            "file_size_bytes": file_size,
            "graph_write_allowed": False,
            "local_file_sha256": full_hash if recovery.HASH64_RE.match(full_hash) else "",
            "memory_write_allowed": False,
            "platform": artifact.get("platform") or row.get("platform") or "unknown",
            "public_serving_field_allowed": False,
            "serving_dj_id_bound": False,
            "serving_rebuild_allowed": False,
            "source_raw_db_write_allowed": False,
            "storage_write_allowed_now": False,
            "write_execution_allowed_now": False,
        }
        if blockers:
            blocked = dict(base)
            blocked["blockers"] = blockers
            blocked["storage_contract_status"] = "storage_contract_blocked_report_only"
            blocked_rows.append(blocked)
            continue
        key = storage_key(full_hash)
        ready = dict(base)
        ready.update(
            {
                "blockers": [
                    "storage_write_gate_required",
                    "serving_dj_id_binding_required",
                    "public_display_gate_closed",
                ],
                "content_addressed_storage_key_hash": recovery.stable_hash(key, 24),
                "content_addressed_storage_key_preview": f"atlas-avatar-sha256/{full_hash[:2]}/{full_hash[:12]}...",
                "readback_selector_hash": recovery.stable_hash(f"{row.get('avatar_id_hash')}|{full_hash}|{file_size}", 24),
                "rollback_selector_hash": recovery.stable_hash(f"rollback|{row.get('avatar_id_hash')}|{full_hash}", 24),
                "storage_contract_ready": True,
                "storage_contract_status": "storage_contract_ready_report_only",
            }
        )
        ready_rows.append(ready)
    return ready_rows, blocked_rows


def write_report(path: Path, summary: dict[str, Any], contract_path: Path, ready_path: Path, blocked_path: Path) -> None:
    counts = summary["counts"]
    lines = [
        "# Atlas T6 Avatar Storage Contract Gate 20260527",
        "",
        f"Generated: `{summary['generated_at']}`",
        "",
        "## Decision",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Input avatar rows: `{counts['input_avatar_rows']}`",
        f"- Storage-contract ready / blocked rows: `{counts['storage_contract_ready_rows']}/{counts['storage_contract_blocked_rows']}`",
        f"- DJ-first / non-DJ ready rows: `{counts['dj_first_storage_ready_rows']}/{counts['non_dj_storage_ready_rows']}`",
        f"- Leak hits public URL / sensitive key / local path: `{summary['leak_scan']['public_url_hits']}/{summary['leak_scan']['sensitive_key_hits']}/{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Boundary Truth",
        "",
        "- Report-only content-addressed storage contract; no binary files were opened and no storage was written.",
        "- Source/raw DB, serving SQLite, graph/vector, public pointer, huaidj.club, mini-program, memory, network/model/OCR, 9router, and D: root actions remain untouched.",
        "- Public avatar display remains closed until storage write/readback, serving DJ ID binding, local serving rebuild, UI/API smoke, rollback evidence, and explicit public-serving gate pass.",
        "",
        "## Evidence",
        "",
        f"- Contract: `{recovery.display_path(contract_path)}`",
        f"- Ready rows: `{recovery.display_path(ready_path)}`",
        f"- Blocked rows: `{recovery.display_path(blocked_path)}`",
        "",
        "## Next Resume Pointer",
        "",
        f"`{summary['next_resume_pointer']}`",
        "",
    ]
    recovery.write_text(path, "\n".join(lines))


def build(args: argparse.Namespace) -> dict[str, Any]:
    recovery_dir = Path(args.recovery_dir)
    manifest_dir = Path(args.manifest_dir)
    out_dir = Path(args.out_dir)
    report_path = Path(args.report)

    recovery_rows = recovery.read_jsonl(recovery_dir / "avatar_recovery_rows.jsonl", "avatar recovery rows")
    recovery_summary = recovery.read_json(recovery_dir / "avatar_media_recovery_summary.json", "avatar recovery summary")
    artifacts_by_avatar_hash = load_avatar_artifact_index(manifest_dir)

    hash_rows = [row for row in recovery_rows if row.get("hash_addressable")]
    ready_rows, blocked_rows = build_contract_rows(hash_rows, artifacts_by_avatar_hash)

    ready_path = out_dir / "avatar_storage_contract_ready_report_only.jsonl"
    blocked_path = out_dir / "avatar_storage_contract_blocked_rows.jsonl"
    contract_path = out_dir / "avatar_storage_contract.json"
    summary_path = out_dir / "avatar_storage_contract_summary.json"
    leak_path = out_dir / "leak_scan.json"
    summary_md_path = out_dir / "avatar_storage_contract_summary.md"

    contract = {
        "schema_version": f"{SCHEMA_VERSION}.contract",
        "generated_at": now_iso(),
        "decision": "atlas_t6_avatar_storage_contract_gate_ready_report_only",
        "report_only": True,
        "source_recovery_decision": recovery_summary.get("decision"),
        "storage_policy": {
            "content_addressing": "local_file_sha256",
            "object_key_template": "atlas-avatar-sha256/<sha256-prefix>/<sha256>",
            "raw_urls_emitted": False,
            "local_paths_emitted": False,
            "binary_read_required_before_write": True,
            "public_display_fields_stay_closed": True,
        },
        "prewrite_requirements": [
            "open only an explicit binary artifact source or storage staging root in bounded mode",
            "verify full local_file_sha256 and file_size before writing storage",
            "bind DJ-first rows to an Atlas dj_id before serving avatar display",
            "route non-DJ rows to entity media policy or exclude from DJ profile avatar display",
            "materialize inverse rollback selectors for every storage object and serving row",
        ],
        "postwrite_requirements": [
            "read back storage object checksum and byte size",
            "rebuild a local serving candidate with avatar/media deltas only after binding passes",
            "run local UI/API smoke before any public-serving field promotion",
        ],
        "write_guards": WRITE_GUARDS,
    }

    counts = {
        "input_avatar_rows": len(hash_rows),
        "storage_contract_ready_rows": len(ready_rows),
        "storage_contract_blocked_rows": len(blocked_rows),
        "dj_first_storage_ready_rows": sum(1 for row in ready_rows if row.get("dj_first_candidate")),
        "non_dj_storage_ready_rows": sum(1 for row in ready_rows if not row.get("dj_first_candidate")),
        "public_serving_field_allowed_rows": 0,
        "source_raw_db_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "storage_write_allowed_now_rows": 0,
        "memory_write_allowed_rows": 0,
    }
    leak_payload = {
        "contract": contract,
        "ready_rows": ready_rows,
        "blocked_rows": blocked_rows,
    }
    leak_scan = recovery.leak_counts_for(leak_payload)
    failed_checks: list[str] = []
    if blocked_rows:
        failed_checks.append("storage_contract_blocked_rows_present")
    if any(leak_scan.values()):
        failed_checks.append("leak_scan_hits_present")

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": contract["generated_at"],
        "decision": "atlas_t6_avatar_storage_contract_gate_blocked_report_only" if failed_checks else "atlas_t6_avatar_storage_contract_gate_ready_report_only",
        "failed_checks": failed_checks,
        "counts": counts,
        "platform_counts_top": recovery.top_counts(Counter(str(row.get("platform") or "unknown") for row in ready_rows)),
        "entity_kind_counts_top": recovery.top_counts(Counter(str(row.get("entity_kind") or "unknown") for row in ready_rows)),
        "leak_scan": leak_scan,
        "write_guards": WRITE_GUARDS,
        "inputs": {
            "recovery_summary": recovery.display_path(recovery_dir / "avatar_media_recovery_summary.json"),
            "recovery_rows": recovery.display_path(recovery_dir / "avatar_recovery_rows.jsonl"),
            "v4_avatar_artifacts": recovery.display_path(manifest_dir / "avatar_artifacts_manifest.jsonl"),
        },
        "outputs": {
            "contract": recovery.display_path(contract_path),
            "ready_rows": recovery.display_path(ready_path),
            "blocked_rows": recovery.display_path(blocked_path),
            "summary": recovery.display_path(summary_path),
            "report": recovery.display_path(report_path),
        },
        "stop_reason": "avatar_storage_contract_ready_report_only_binding_and_write_gate_required",
        "wait_reason": "Next gate must bind DJ-first rows to Atlas dj_id and open only explicit storage/binary target with checksum readback before any serving/public avatar field.",
        "next_resume_pointer": recovery.display_path(ready_path),
    }

    recovery.write_json(contract_path, contract)
    recovery.write_jsonl(ready_path, ready_rows)
    recovery.write_jsonl(blocked_path, blocked_rows)
    recovery.write_json(leak_path, leak_scan)
    recovery.write_json(summary_path, summary)
    write_report(report_path, summary, contract_path, ready_path, blocked_path)
    recovery.write_text(summary_md_path, f"# Avatar Storage Contract Summary\n\nDecision: `{summary['decision']}`\n\nNext: `{summary['next_resume_pointer']}`\n")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recovery-dir", default=str(DEFAULT_RECOVERY_DIR))
    parser.add_argument("--manifest-dir", default=str(DEFAULT_MANIFEST_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    return parser.parse_args()


def main() -> None:
    summary = build(parse_args())
    print(json_summary(summary))


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


if __name__ == "__main__":
    main()
