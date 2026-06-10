#!/usr/bin/env python3
"""Build a report-only prewrite snapshot packet for manual participant DB targets."""
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
DEFAULT_GATE_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_db_write_gate_q6_20260526"
DEFAULT_TARGETS = DEFAULT_GATE_DIR / "manual_participant_db_write_gate_targets.jsonl"
DEFAULT_GATE_SUMMARY = DEFAULT_GATE_DIR / "manual_participant_db_write_gate_summary.json"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_db_prewrite_snapshot_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_DB_PREWRITE_SNAPSHOT_PACKET_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_db_prewrite_snapshot.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for manual participant prewrite snapshot packet: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


def read_json(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return value if isinstance(value, dict) else {}


def read_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    reject_d_path(path, label)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: expected object row")
            rows.append(value)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
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
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def list_strings(value: Any, limit: int = 200) -> list[str]:
    if not isinstance(value, list):
        return []
    return [compact(item, limit) for item in value if compact(item, limit)]


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def scan_payload(rows: list[dict[str, Any]]) -> dict[str, int]:
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    return {
        "public_url_hits": len(URL_RE.findall(text)),
        "sensitive_key_hits": len(SECRET_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
    }


def target_blockers(row: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    selector = dict_value(row.get("target_selector"))
    evidence = dict_value(row.get("evidence_contract"))
    prewrite = dict_value(row.get("prewrite_snapshot_contract"))
    rollback = dict_value(row.get("rollback_contract"))
    postwrite = dict_value(row.get("postwrite_readback_contract"))

    if compact(row.get("gate_status")) != "manual_participant_db_write_gate_ready_report_only":
        blockers.append("gate_status_not_ready")
    if compact(row.get("write_status")) != "report_only":
        blockers.append("write_status_not_report_only")
    if row.get("write_execution_allowed_now") is not False:
        blockers.append("write_execution_allowed_now_not_false")
    for key in [
        "accepted_for_graph",
        "source_sqlite_write_allowed",
        "serving_rebuild_allowed",
        "graph_write_allowed",
        "public_serving_field_allowed",
        "memory_write_allowed",
    ]:
        if row.get(key) is not False:
            blockers.append(f"{key}_not_false")
    if not compact(row.get("selector_hash")):
        blockers.append("selector_hash_missing")
    if not compact(selector.get("representative_event_id"), 180):
        blockers.append("representative_event_id_missing")
    if len(list_strings(selector.get("original_event_ids"), 180)) < 2:
        blockers.append("original_event_ids_need_multiple_ids")
    if prewrite.get("required") is not True:
        blockers.append("prewrite_snapshot_contract_not_required")
    if prewrite.get("must_record_row_hashes") is not True:
        blockers.append("prewrite_row_hash_requirement_missing")
    if rollback.get("required") is not True or rollback.get("inverse_mapping_required") is not True:
        blockers.append("rollback_contract_not_required")
    if postwrite.get("required") is not True:
        blockers.append("postwrite_readback_contract_not_required")
    if int(evidence.get("participant_evidence_total") or 0) <= 0:
        blockers.append("participant_evidence_total_not_positive")
    if int(evidence.get("merge_edge_count") or 0) != max(0, len(list_strings(selector.get("original_event_ids"), 180)) - 1):
        blockers.append("merge_edge_count_mismatch")
    return sorted(set(blockers))


def build_snapshot_row(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    selector = dict_value(row.get("target_selector"))
    evidence = dict_value(row.get("evidence_contract"))
    prewrite = dict_value(row.get("prewrite_snapshot_contract"))
    original_event_ids = list_strings(selector.get("original_event_ids"), 180)
    source_ref_ids = list_strings(selector.get("source_ref_ids"), 180)
    row_hash = sha256_json(row)
    return {
        "schema_version": SCHEMA_VERSION + ".snapshot_row",
        "generated_at": generated_at,
        "snapshot_status": "manual_participant_db_prewrite_snapshot_materialized_report_only",
        "selector_hash": compact(row.get("selector_hash"), 100),
        "contract_row_sha256": row_hash,
        "review_lane": compact(row.get("review_lane"), 100),
        "consolidation_review_id": compact(row.get("consolidation_review_id"), 160),
        "source_account": compact(row.get("source_account"), 220),
        "article_uid": compact(row.get("article_uid"), 260),
        "work_item_id": compact(row.get("work_item_id"), 140),
        "target_namespace": compact(row.get("target_namespace"), 180),
        "snapshot_scope": {
            "representative_event_id": compact(selector.get("representative_event_id"), 180),
            "original_event_ids": original_event_ids,
            "non_representative_event_ids": list_strings(selector.get("non_representative_event_ids"), 180),
            "source_ref_ids": source_ref_ids,
            "source_hash": compact(selector.get("source_hash"), 180),
        },
        "contract_counts": {
            "event_row_count": int(evidence.get("event_row_count") or 0),
            "merge_edge_count": int(evidence.get("merge_edge_count") or 0),
            "participant_evidence_total": int(evidence.get("participant_evidence_total") or 0),
            "original_event_id_count": len(original_event_ids),
            "source_ref_id_count": len(source_ref_ids),
        },
        "prewrite_snapshot_manifest": {
            "source_db_opened": False,
            "mode": "contract_snapshot_only_before_any_later_write",
            "minimum_snapshot_tables": list_strings(prewrite.get("minimum_snapshot_tables"), 240),
            "row_hash_algorithm": "sha256(canonical_json)",
            "must_capture_real_db_rows_before_confirmed_writer": True,
        },
        "dry_run_prewrite_work_order": {
            "execution_allowed_now": False,
            "source_raw_db_write_allowed_now": False,
            "requires_explicit_target_db": True,
            "requires_confirm_token": True,
            "would_touch_event_ids": original_event_ids,
            "would_validate_source_refs": source_ref_ids,
        },
        "rollback_contract_sha256": sha256_json(dict_value(row.get("rollback_contract"))),
        "postwrite_readback_contract_sha256": sha256_json(dict_value(row.get("postwrite_readback_contract"))),
        "accepted_for_graph": False,
        "source_sqlite_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_execution_allowed_now": False,
    }


def upstream_failures(gate_summary: dict[str, Any], targets: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    counts = dict_value(gate_summary.get("counts"))
    leaks = dict_value(gate_summary.get("leak_counts"))
    if gate_summary.get("decision") != "atlas_social_manual_participant_db_write_gate_ready_report_only":
        failures.append("upstream_db_write_gate_not_ready")
    try:
        upstream_targets = int(counts.get("write_gate_target_rows") or -1)
    except (TypeError, ValueError):
        upstream_targets = -1
    if upstream_targets != len(targets):
        failures.append("upstream_target_count_mismatch")
    if int(counts.get("blocked_rows") or 0) != 0:
        failures.append("upstream_blocked_rows_not_zero")
    if any(int(leaks.get(key) or 0) for key in ["public_url_hits", "sensitive_key_hits", "local_path_hits"]):
        failures.append("upstream_leak_counts_not_zero")
    return failures


def build_packet(targets_path: Path, gate_summary_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    generated_at = now_iso()
    target_rows = read_jsonl(targets_path, "write_gate_targets")
    gate_summary = read_json(gate_summary_path)

    snapshots: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for row in target_rows:
        blockers = target_blockers(row)
        if blockers:
            blocked.append(
                {
                    "schema_version": SCHEMA_VERSION + ".blocked_row",
                    "generated_at": generated_at,
                    "selector_hash": compact(row.get("selector_hash"), 100),
                    "consolidation_review_id": compact(row.get("consolidation_review_id"), 160),
                    "blockers": blockers,
                    "write_execution_allowed_now": False,
                }
            )
        else:
            snapshots.append(build_snapshot_row(row, generated_at))

    upstream = upstream_failures(gate_summary, target_rows)
    leak_counts = scan_payload(snapshots + blocked)
    duplicate_hashes = sorted(
        item for item, count in Counter(row["contract_row_sha256"] for row in snapshots).items() if count > 1
    )
    failed_checks: list[str] = []
    failed_checks.extend(upstream)
    if blocked:
        failed_checks.append("prewrite_snapshot_blocked_rows")
    if duplicate_hashes:
        failed_checks.append("duplicate_contract_row_hashes")
    failed_checks.extend(key for key, value in leak_counts.items() if value)
    decision = (
        "atlas_social_manual_participant_db_prewrite_snapshot_ready_report_only"
        if snapshots and not failed_checks
        else "atlas_social_manual_participant_db_prewrite_snapshot_blocked_report_only"
    )

    total_event_ids = {
        event_id
        for row in snapshots
        for event_id in row["snapshot_scope"]["original_event_ids"]
    }
    lane_counts = Counter(row["review_lane"] for row in snapshots)
    counts = {
        "input_target_rows": len(target_rows),
        "prewrite_snapshot_rows": len(snapshots),
        "blocked_rows": len(blocked),
        "event_id_snapshot_rows": lane_counts.get("event_id_dedupe", 0),
        "semantic_cluster_snapshot_rows": lane_counts.get("semantic_event_cluster", 0),
        "unique_event_ids": len(total_event_ids),
        "planned_identity_lineage_edges_report_only": sum(
            row["contract_counts"]["merge_edge_count"] for row in snapshots
        ),
        "participant_evidence_total": sum(row["contract_counts"]["participant_evidence_total"] for row in snapshots),
        "contract_row_hashes": len({row["contract_row_sha256"] for row in snapshots}),
        "duplicate_contract_row_hashes": len(duplicate_hashes),
        "accepted_for_graph_rows": 0,
        "source_sqlite_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
    }
    outputs = {
        "summary_json": display_path(out_dir / "manual_participant_db_prewrite_snapshot_summary.json"),
        "summary_md": display_path(out_dir / "manual_participant_db_prewrite_snapshot_summary.md"),
        "prewrite_snapshot_rows": display_path(out_dir / "manual_participant_db_prewrite_snapshot_rows.jsonl"),
        "prewrite_snapshot_manifest": display_path(out_dir / "manual_participant_db_prewrite_snapshot_manifest.json"),
        "blocked_rows": display_path(out_dir / "manual_participant_db_prewrite_snapshot_blocked_rows.jsonl"),
        "report": display_path(report_path),
    }
    manifest = {
        "schema_version": SCHEMA_VERSION + ".manifest",
        "generated_at": generated_at,
        "decision": decision,
        "snapshot_row_count": len(snapshots),
        "contract_row_hashes": [row["contract_row_sha256"] for row in snapshots],
        "source_db_opened": False,
        "source_raw_db_write_executed": False,
        "serving_sqlite_write_or_rebuild_executed": False,
        "next_required_gate": "future confirmed writer must open the explicit target DB read-only, capture real row snapshots, then require a separate write confirmation",
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": sorted(set(failed_checks)),
        "counts": counts,
        "leak_counts": leak_counts,
        "inputs": {
            "write_gate_targets": display_path(targets_path),
            "write_gate_summary": display_path(gate_summary_path),
        },
        "outputs": outputs,
        "upstream_failures": upstream,
        "duplicate_contract_row_hashes": duplicate_hashes,
        "write_guards": {
            "write_execution_allowed_now": False,
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
        },
        "boundary": {
            "report_only": True,
            "source_db_opened": False,
            "source_raw_db_write_executed": False,
            "serving_sqlite_write_or_rebuild_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_sqlite_write_executed": False,
            "public_pointer_update_executed": False,
            "deploy_executed": False,
            "mini_program_upload_or_review_executed": False,
            "memory_write_executed": False,
            "network_call_executed": False,
            "model_call_executed": False,
            "credential_read_executed": False,
            "d_root_scan_executed": False,
        },
        "next_cursor": outputs["prewrite_snapshot_rows"],
        "next_gate": manifest["next_required_gate"],
    }

    write_jsonl(out_dir / "manual_participant_db_prewrite_snapshot_rows.jsonl", snapshots)
    write_jsonl(out_dir / "manual_participant_db_prewrite_snapshot_blocked_rows.jsonl", blocked)
    write_json(out_dir / "manual_participant_db_prewrite_snapshot_manifest.json", manifest)
    write_json(out_dir / "manual_participant_db_prewrite_snapshot_summary.json", summary)
    write_text(out_dir / "manual_participant_db_prewrite_snapshot_summary.md", render_summary(summary))
    write_text(report_path, render_report(summary))
    return summary


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Atlas T6 Manual Participant DB Prewrite Snapshot Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Input target rows: `{counts['input_target_rows']}`",
            f"- Prewrite snapshot rows: `{counts['prewrite_snapshot_rows']}`",
            f"- Blocked rows: `{counts['blocked_rows']}`",
            f"- Event-id / semantic split: `{counts['event_id_snapshot_rows']}/{counts['semantic_cluster_snapshot_rows']}`",
            f"- Unique event_ids: `{counts['unique_event_ids']}`",
            f"- Contract row hashes: `{counts['contract_row_hashes']}`",
            "- Source DB opened/written: `false/false`.",
            f"- Next cursor: `{summary['next_cursor']}`",
            "",
        ]
    )


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    leak = summary["leak_counts"]
    outputs = summary["outputs"]
    return "\n".join(
        [
            "# Atlas T6 Manual Participant DB Prewrite Snapshot Packet - 2026-05-26",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            "- Boundary: report-only prewrite snapshot packet. It hashes the manual participant write-gate contracts and emits dry-run snapshot work orders. It does not open source/raw DBs and does not execute source DB, serving SQLite, graph/vector, public, deploy, upload/review, or memory writes.",
            "",
            "## Counts",
            "",
            f"- Input target rows: `{counts['input_target_rows']}`",
            f"- Prewrite snapshot rows: `{counts['prewrite_snapshot_rows']}`",
            f"- Blocked rows: `{counts['blocked_rows']}`",
            f"- Event-id / semantic snapshot split: `{counts['event_id_snapshot_rows']}/{counts['semantic_cluster_snapshot_rows']}`",
            f"- Unique event_ids: `{counts['unique_event_ids']}`",
            f"- Planned identity-lineage edges, report-only: `{counts['planned_identity_lineage_edges_report_only']}`",
            f"- Participant evidence total: `{counts['participant_evidence_total']}`",
            f"- Contract row hashes / duplicate hashes: `{counts['contract_row_hashes']}/{counts['duplicate_contract_row_hashes']}`",
            "- Accepted/source-sqlite/serving/graph/public/memory rows: `0/0/0/0/0/0`",
            f"- Public URL / sensitive key / local path leak hits: `{leak['public_url_hits']}/{leak['sensitive_key_hits']}/{leak['local_path_hits']}`",
            "",
            "## Evidence",
            "",
            f"- Summary JSON: `{outputs['summary_json']}`",
            f"- Snapshot rows: `{outputs['prewrite_snapshot_rows']}`",
            f"- Snapshot manifest: `{outputs['prewrite_snapshot_manifest']}`",
            f"- Blocked rows: `{outputs['blocked_rows']}`",
            "",
            "## Next Cursor",
            "",
            f"`{summary['next_cursor']}`",
            "",
            "A later confirmed writer must still open the explicit target DB read-only, capture real row snapshots, then require a separate write confirmation. This packet is not mutation authorization.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    parser.add_argument("--gate-summary", type=Path, default=DEFAULT_GATE_SUMMARY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(args.targets, args.gate_summary, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["decision"].endswith("_ready_report_only") else 1


if __name__ == "__main__":
    raise SystemExit(main())
