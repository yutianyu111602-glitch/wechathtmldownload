#!/usr/bin/env python3
"""Build a report-only Q6 manual participant event consolidation gate packet."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_REVIEW_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_event_cluster_review_q6_20260526"
DEFAULT_EVENT_ID_CANDIDATES = DEFAULT_REVIEW_DIR / "event_id_consolidation_candidates.jsonl"
DEFAULT_SEMANTIC_CANDIDATES = DEFAULT_REVIEW_DIR / "semantic_cluster_consolidation_candidates.jsonl"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_consolidation_gate_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_CONSOLIDATION_GATE_PACKET_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_consolidation_gate_packet.v1"

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
        raise ValueError(f"{label} must not point to D: for Q6 consolidation gate packet: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


def read_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    reject_d_path(path, label)
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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
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


def event_ids(row: dict[str, Any]) -> list[str]:
    return sorted({compact(item, 120) for item in row.get("event_ids_for_consolidation_review", []) if compact(item, 120)})


def semantic_clusters(row: dict[str, Any]) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for cluster in row.get("semantic_event_clusters") or []:
        if isinstance(cluster, dict):
            clusters.append(cluster)
    return clusters


def source_ref_ids(row: dict[str, Any]) -> list[str]:
    refs = {compact(row.get("source_ref_id"), 120)}
    for cluster in semantic_clusters(row):
        refs.update(compact(item, 120) for item in cluster.get("source_ref_ids", []) if compact(item, 120))
    refs.discard("")
    return sorted(refs)


def semantic_cluster_ids(row: dict[str, Any]) -> list[str]:
    return sorted({compact(cluster.get("cluster_id"), 120) for cluster in semantic_clusters(row) if compact(cluster.get("cluster_id"), 120)})


def selector_payload(row: dict[str, Any], lane: str, ids: list[str], representative: str) -> dict[str, Any]:
    selector = {
        "selector_type": lane,
        "representative_event_id_review_only": representative,
        "candidate_event_ids": ids,
        "candidate_event_id_count": len(ids),
        "source_account": compact(row.get("source_account"), 220),
        "article_uid": compact(row.get("article_uid"), 260),
        "source_ref_ids": source_ref_ids(row),
        "source_hash": compact(row.get("source_hash"), 120),
        "post_date": compact(row.get("post_date"), 80),
        "semantic_cluster_ids": semantic_cluster_ids(row),
    }
    material = json.dumps(selector, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    selector["selector_hash"] = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return selector


def row_failures(row: dict[str, Any], expected_status: str) -> list[str]:
    failures: list[str] = []
    if compact(row.get("review_status")) != expected_status:
        failures.append("review_status_not_expected")
    if expected_status == "event_id_consolidation_candidate_report_only" and row.get("event_id_consolidation_candidate") is not True:
        failures.append("event_id_consolidation_candidate_not_true")
    if expected_status == "semantic_cluster_consolidation_candidate_report_only" and row.get("semantic_cluster_consolidation_candidate") is not True:
        failures.append("semantic_cluster_consolidation_candidate_not_true")
    if compact(row.get("blocking_reason")) != "none":
        failures.append("blocking_reason_not_none")
    if len(set(event_ids(row))) <= 1:
        failures.append("event_ids_for_consolidation_not_duplicate")
    if not compact(row.get("representative_event_id_review_only")):
        failures.append("representative_event_id_missing")
    for key in [
        "accepted_for_graph",
        "source_sqlite_write_allowed",
        "serving_rebuild_allowed",
        "graph_write_allowed",
        "public_serving_field_allowed",
        "memory_write_allowed",
    ]:
        if row.get(key) is not False:
            failures.append(f"{key}_not_false")
    if compact(row.get("write_status")) != "report_only":
        failures.append("write_status_not_report_only")
    return failures


def packet_target(row: dict[str, Any], lane: str, failures: list[str], generated_at: str) -> dict[str, Any]:
    ready = not failures
    ids = event_ids(row)
    representative = compact(row.get("representative_event_id_review_only"), 120)
    selector = selector_payload(row, lane, ids, representative)
    return {
        "schema_version": SCHEMA_VERSION + ".target_row",
        "generated_at": generated_at,
        "review_lane": lane,
        "gate_status": "consolidation_target_ready_for_manual_db_readback_report_only"
        if ready
        else "consolidation_target_blocked_before_db_readback",
        "gate_failures": failures,
        "consolidation_review_id": compact(row.get("consolidation_review_id"), 120),
        "source_account": compact(row.get("source_account"), 220),
        "article_uid": compact(row.get("article_uid"), 260),
        "work_item_id": compact(row.get("work_item_id"), 100),
        "source_ref_id": compact(row.get("source_ref_id"), 120),
        "source_hash": compact(row.get("source_hash"), 120),
        "post_date": compact(row.get("post_date"), 80),
        "title": compact(row.get("title"), 300),
        "name": compact(row.get("name"), 220),
        "candidate_rows": int(row.get("candidate_rows") or 0),
        "participant_sample_rows": int(row.get("participant_sample_rows") or 0),
        "event_ids_for_consolidation_review": ids,
        "representative_event_id_review_only": representative,
        "deterministic_selector": selector,
        "selector_hash": selector["selector_hash"],
        "db_readback_contract": {
            "required": True,
            "mode": "read_only_prewrite",
            "selectors": {
                "event_ids": ids,
                "source_ref_ids": selector["source_ref_ids"],
                "source_hash": selector["source_hash"],
                "article_uid": selector["article_uid"],
            },
            "must_verify_fields": [
                "event_id",
                "title_or_name",
                "starts_at",
                "city",
                "venue_name",
                "source_ref_ids",
                "participant_evidence_count",
            ],
        },
        "planned_consolidation_action": "manual_db_readback_then_event_identity_alias_or_merge"
        if lane == "event_id_dedupe"
        else "manual_db_readback_then_semantic_event_cluster_alias_or_merge",
        "prewrite_checks_required": [
            "read all candidate event rows by event_id",
            "verify shared source_ref_id/source_hash/article_uid context",
            "verify date/city/venue/title compatibility from source evidence",
            "verify no already-promoted conflicting public serving field",
        ],
        "rollback_requirement": "Any later write packet must include exact inverse mapping from representative event_id back to original event_ids.",
        "rollback_contract": {
            "required": True,
            "inverse_mapping_required": True,
            "representative_event_id_review_only": representative,
            "original_event_ids": ids,
            "prewrite_snapshot_required": True,
            "postwrite_readback_required": True,
        },
        "accepted_for_graph": False,
        "source_sqlite_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_status": "report_only",
        "next_gate": "Build an explicit DB-backed write packet with readback and rollback before source/serving/graph mutation.",
    }


def scan_payload(rows: list[dict[str, Any]]) -> dict[str, int]:
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    return {
        "public_url_hits": len(URL_RE.findall(text)),
        "sensitive_key_hits": len(SECRET_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
    }


def build_packet(
    event_id_candidates_path: Path,
    semantic_candidates_path: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    generated_at = now_iso()
    event_rows = read_jsonl(event_id_candidates_path, "event_id_candidates")
    semantic_rows = read_jsonl(semantic_candidates_path, "semantic_candidates")

    targets: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for row in event_rows:
        failures = row_failures(row, "event_id_consolidation_candidate_report_only")
        target = packet_target(row, "event_id_dedupe", failures, generated_at)
        targets.append(target)
        if failures:
            blocked.append(target)
    for row in semantic_rows:
        failures = row_failures(row, "semantic_cluster_consolidation_candidate_report_only")
        for key in ["cluster_date_consistent", "cluster_venue_consistent", "cluster_city_consistent"]:
            if row.get(key) is not True:
                failures.append(f"{key}_not_true")
        if float(row.get("cluster_title_min_similarity") or 0) < 0.72:
            failures.append("cluster_title_similarity_below_gate")
        target = packet_target(row, "semantic_event_cluster", failures, generated_at)
        target["cluster_date_consistent"] = bool(row.get("cluster_date_consistent"))
        target["cluster_venue_consistent"] = bool(row.get("cluster_venue_consistent"))
        target["cluster_city_consistent"] = bool(row.get("cluster_city_consistent"))
        target["cluster_title_min_similarity"] = float(row.get("cluster_title_min_similarity") or 0)
        targets.append(target)
        if failures:
            blocked.append(target)

    ready_candidates = [row for row in targets if not row["gate_failures"]]
    ready_targets: list[dict[str, Any]] = []
    duplicate_selector_rows: list[dict[str, Any]] = []
    seen_selector_hashes: set[str] = set()
    for row in ready_candidates:
        selector_hash = row["selector_hash"]
        if selector_hash in seen_selector_hashes:
            duplicate_row = dict(row)
            duplicate_row["gate_status"] = "duplicate_selector_collapsed_report_only"
            duplicate_row["next_gate"] = "Use the first row with this selector_hash for readback; keep this row as duplicate selector evidence only."
            duplicate_selector_rows.append(duplicate_row)
            continue
        seen_selector_hashes.add(selector_hash)
        ready_targets.append(row)
    ready_event_id_targets = [row for row in ready_targets if row["review_lane"] == "event_id_dedupe"]
    ready_semantic_targets = [row for row in ready_targets if row["review_lane"] == "semantic_event_cluster"]
    selector_counts = Counter(row["selector_hash"] for row in ready_candidates)
    duplicate_selector_hashes = sorted([selector_hash for selector_hash, count in selector_counts.items() if count > 1])
    leak_counts = scan_payload(targets)
    failed_checks = [key for key, value in leak_counts.items() if value]
    if blocked:
        failed_checks.append("blocked_candidate_rows")
    decision = (
        "atlas_social_manual_participant_consolidation_gate_packet_ready_report_only"
        if not failed_checks
        else "atlas_social_manual_participant_consolidation_gate_packet_blocked_report_only"
    )

    counts = {
        "input_event_id_candidate_rows": len(event_rows),
        "input_semantic_cluster_candidate_rows": len(semantic_rows),
        "consolidation_gate_target_rows": len(targets),
        "ready_before_selector_dedupe_rows": len(ready_candidates),
        "ready_for_manual_db_readback_rows": len(ready_targets),
        "event_id_ready_for_manual_db_readback_rows": len(ready_event_id_targets),
        "semantic_cluster_ready_for_manual_db_readback_rows": len(ready_semantic_targets),
        "blocked_candidate_rows": len(blocked),
        "duplicate_selector_groups": len(duplicate_selector_hashes),
        "duplicate_selector_collapsed_rows": len(duplicate_selector_rows),
        "accepted_for_graph_rows": 0,
        "source_sqlite_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "counts": counts,
        "leak_counts": leak_counts,
        "inputs": {
            "event_id_candidates": display_path(event_id_candidates_path),
            "semantic_candidates": display_path(semantic_candidates_path),
        },
        "outputs": {
            "consolidation_gate_targets": display_path(out_dir / "consolidation_gate_targets.jsonl"),
            "ready_for_manual_db_readback": display_path(out_dir / "ready_for_manual_db_readback.jsonl"),
            "event_id_ready_for_manual_db_readback": display_path(out_dir / "event_id_ready_for_manual_db_readback.jsonl"),
            "semantic_cluster_ready_for_manual_db_readback": display_path(out_dir / "semantic_cluster_ready_for_manual_db_readback.jsonl"),
            "duplicate_selector_collapsed_rows": display_path(out_dir / "duplicate_selector_collapsed_rows.jsonl"),
            "blocked_before_db_readback": display_path(out_dir / "blocked_before_db_readback.jsonl"),
            "summary_json": display_path(out_dir / "manual_participant_consolidation_gate_summary.json"),
            "report": display_path(report_path),
        },
        "write_guards": {
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
        },
        "selector_dedupe_policy": {
            "duplicate_selector_hashes": duplicate_selector_hashes,
            "policy": "Identical deterministic selectors are collapsed before DB readback to prevent duplicate later write packets; collapsed rows remain report-only evidence.",
        },
        "next_cursor": display_path(out_dir / "ready_for_manual_db_readback.jsonl"),
        "next_cursor_split": {
            "event_id_first": display_path(out_dir / "event_id_ready_for_manual_db_readback.jsonl"),
            "semantic_cluster_second": display_path(out_dir / "semantic_cluster_ready_for_manual_db_readback.jsonl"),
        },
    }

    write_jsonl(out_dir / "consolidation_gate_targets.jsonl", targets)
    write_jsonl(out_dir / "ready_for_manual_db_readback.jsonl", ready_targets)
    write_jsonl(out_dir / "event_id_ready_for_manual_db_readback.jsonl", ready_event_id_targets)
    write_jsonl(out_dir / "semantic_cluster_ready_for_manual_db_readback.jsonl", ready_semantic_targets)
    write_jsonl(out_dir / "duplicate_selector_collapsed_rows.jsonl", duplicate_selector_rows)
    write_jsonl(out_dir / "blocked_before_db_readback.jsonl", blocked)
    write_json(out_dir / "manual_participant_consolidation_gate_summary.json", summary)
    write_text(out_dir / "manual_participant_consolidation_gate_summary.md", render_summary(summary))
    write_text(report_path, render_report(summary))
    return summary


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Atlas T6 Manual Participant Consolidation Gate Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Event-id candidates: `{counts['input_event_id_candidate_rows']}`",
            f"- Semantic cluster candidates: `{counts['input_semantic_cluster_candidate_rows']}`",
            f"- Ready before selector dedupe: `{counts['ready_before_selector_dedupe_rows']}`",
            f"- Ready for manual DB readback: `{counts['ready_for_manual_db_readback_rows']}`",
            f"- Event-id / semantic ready split: `{counts['event_id_ready_for_manual_db_readback_rows']}/{counts['semantic_cluster_ready_for_manual_db_readback_rows']}`",
            f"- Blocked before DB readback: `{counts['blocked_candidate_rows']}`",
            f"- Duplicate selector groups / collapsed rows: `{counts['duplicate_selector_groups']}/{counts['duplicate_selector_collapsed_rows']}`",
            "- Write guards: source SQLite, serving rebuild, graph write, public serving field, and memory write all remain `false`.",
            f"- Next cursor: `{summary['next_cursor']}`",
            f"- Split cursor: `{summary['next_cursor_split']}`",
            "",
        ]
    )


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    leak = summary["leak_counts"]
    outputs = summary["outputs"]
    return "\n".join(
        [
            "# Atlas T6 Manual Participant Consolidation Gate Packet - 2026-05-26",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            "- Boundary: report-only packet. It does not accept graph facts, mutate source/raw Atlas DB, rebuild serving SQLite, write Neo4j/Qdrant/SQLite production state, update public pointers, deploy CloudRun/VPS, upload/review mini-program, or write memory.",
            "",
            "## Counts",
            "",
            f"- Input event-id consolidation candidates: `{counts['input_event_id_candidate_rows']}`",
            f"- Input semantic cluster consolidation candidates: `{counts['input_semantic_cluster_candidate_rows']}`",
            f"- Consolidation gate targets: `{counts['consolidation_gate_target_rows']}`",
            f"- Ready before selector dedupe: `{counts['ready_before_selector_dedupe_rows']}`",
            f"- Ready for manual DB readback: `{counts['ready_for_manual_db_readback_rows']}`",
            f"- Event-id / semantic ready split: `{counts['event_id_ready_for_manual_db_readback_rows']}/{counts['semantic_cluster_ready_for_manual_db_readback_rows']}`",
            f"- Blocked before DB readback: `{counts['blocked_candidate_rows']}`",
            f"- Duplicate selector groups / collapsed rows: `{counts['duplicate_selector_groups']}/{counts['duplicate_selector_collapsed_rows']}`",
            "- Accepted/source-sqlite/serving/graph/public/memory rows: `0/0/0/0/0/0`",
            f"- Public URL / sensitive key / local path leak hits: `{leak['public_url_hits']}/{leak['sensitive_key_hits']}/{leak['local_path_hits']}`",
            "",
            "## Evidence",
            "",
            f"- Summary JSON: `{outputs['summary_json']}`",
            f"- Gate targets: `{outputs['consolidation_gate_targets']}`",
            f"- Ready cursor: `{outputs['ready_for_manual_db_readback']}`",
            f"- Event-id ready cursor: `{outputs['event_id_ready_for_manual_db_readback']}`",
            f"- Semantic-cluster ready cursor: `{outputs['semantic_cluster_ready_for_manual_db_readback']}`",
            f"- Duplicate selector evidence: `{outputs['duplicate_selector_collapsed_rows']}`",
            f"- Blocked rows: `{outputs['blocked_before_db_readback']}`",
            "",
            "## Next Cursor",
            "",
            f"`{summary['next_cursor']}`",
            "",
            f"Split order: `{summary['next_cursor_split']['event_id_first']}` then `{summary['next_cursor_split']['semantic_cluster_second']}`.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-id-candidates", type=Path, default=DEFAULT_EVENT_ID_CANDIDATES)
    parser.add_argument("--semantic-candidates", type=Path, default=DEFAULT_SEMANTIC_CANDIDATES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(args.event_id_candidates, args.semantic_candidates, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
