#!/usr/bin/env python3
"""Build a report-only real snapshot gate for mapped source/raw Atlas rows."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_MAPPING_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_source_raw_mapping_probe_q6_20260526"
DEFAULT_MAPPING_ROWS = DEFAULT_MAPPING_DIR / "source_raw_mapping_ready_report_only.jsonl"
DEFAULT_MAPPING_SUMMARY = DEFAULT_MAPPING_DIR / "source_raw_mapping_probe_summary.json"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_mapped_source_raw_real_snapshot_gate_t5_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_MAPPED_SOURCE_RAW_REAL_SNAPSHOT_GATE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_mapped_source_raw_real_snapshot_gate.v1"

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
        raise ValueError(f"{label} must not point to D: for mapped source/raw real snapshot gate: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return value if isinstance(value, dict) else {}


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


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(canonical_json(row))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def list_values(value: Any, limit: int = 220) -> list[str]:
    if not isinstance(value, list):
        return []
    return [compact(item, limit) for item in value if compact(item, limit)]


def int_values(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for item in value:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def scan_payload(payload: Any) -> dict[str, int]:
    text = canonical_json(payload)
    return {
        "public_url_hits": len(URL_RE.findall(text)),
        "sensitive_key_hits": len(SECRET_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
    }


def open_readonly(path: Path) -> sqlite3.Connection:
    reject_d_path(path, "target_db")
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def rows_by_values(conn: sqlite3.Connection, table: str, column: str, values: list[Any], order_by: str) -> list[dict[str, Any]]:
    if not values:
        return []
    placeholders = ",".join("?" for _ in values)
    return [
        {key: row[key] for key in row.keys()}
        for row in conn.execute(
            f'SELECT * FROM "{table}" WHERE "{column}" IN ({placeholders}) ORDER BY {order_by}',
            values,
        )
    ]


def row_blockers(row: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if row.get("source_raw_mapping_ready_report_only") is not True:
        blockers.append("source_raw_mapping_not_ready")
    if compact(row.get("write_status")) != "report_only":
        blockers.append("write_status_not_report_only")
    for key in [
        "accepted_for_graph",
        "source_sqlite_write_allowed",
        "serving_rebuild_allowed",
        "graph_write_allowed",
        "public_serving_field_allowed",
        "memory_write_allowed",
        "write_execution_allowed_now",
    ]:
        if row.get(key) is not False:
            blockers.append(f"{key}_not_false")
    if not compact(row.get("article_uid"), 260):
        blockers.append("article_uid_missing")
    if not int_values(row.get("selected_raw_event_row_pks_report_only")):
        blockers.append("selected_raw_event_row_pks_missing")
    if not list_values(row.get("selected_event_ids_report_only")):
        blockers.append("selected_serving_event_ids_missing")
    if not list_values(row.get("source_ref_ids")):
        blockers.append("source_ref_ids_missing")
    for contract_key in ["prewrite_snapshot_contract", "rollback_contract", "postwrite_readback_contract"]:
        contract = row.get(contract_key) if isinstance(row.get(contract_key), dict) else {}
        if contract.get("required") is not True:
            blockers.append(f"{contract_key}_not_required")
    return sorted(set(blockers))


def build_snapshot(conn: sqlite3.Connection, row: dict[str, Any], target_db_display: str, generated_at: str) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    article_uid = compact(row.get("article_uid"), 260)
    raw_pks = int_values(row.get("selected_raw_event_row_pks_report_only"))
    article_rows = rows_by_values(conn, "articles", "article_uid", [article_uid], "row_pk")
    event_rows = rows_by_values(conn, "events", "row_pk", raw_pks, "row_pk")
    entity_rows = rows_by_values(conn, "entities", "source_article_uid", [article_uid], "row_pk")

    found_pks = {int(item["row_pk"]) for item in event_rows if item.get("row_pk") is not None}
    missing_pks = sorted(set(raw_pks) - found_pks)
    wrong_article_pks = sorted(
        int(item["row_pk"])
        for item in event_rows
        if compact(item.get("source_article_uid"), 260) != article_uid and item.get("row_pk") is not None
    )
    if not article_rows:
        blockers.append("article_row_missing")
    if missing_pks:
        blockers.append("raw_event_rows_missing")
    if wrong_article_pks:
        blockers.append("raw_event_article_uid_mismatch")

    participant_rows = [
        item
        for item in event_rows
        if compact(item.get("participants_json")) not in {"", "[]", "null", "None"}
    ]
    snapshot = {
        "schema_version": SCHEMA_VERSION + ".real_snapshot_row",
        "generated_at": generated_at,
        "target_db": target_db_display,
        "mapping_probe_id": compact(row.get("mapping_probe_id"), 180),
        "upstream_id": compact(row.get("upstream_id"), 180),
        "candidate_lane": compact(row.get("candidate_lane"), 100),
        "source_account": compact(row.get("source_account"), 220),
        "article_uid": article_uid,
        "source_hash": compact(row.get("source_hash"), 180),
        "selected_serving_event_ids_report_only": list_values(row.get("selected_event_ids_report_only"), 180),
        "selected_raw_event_row_pks_report_only": raw_pks,
        "source_ref_ids": list_values(row.get("source_ref_ids"), 180),
        "target_db_rows": {
            "articles": {"count": len(article_rows), "row_hashes": [sha256_json(item) for item in article_rows]},
            "events": {"count": len(event_rows), "row_hashes": [sha256_json(item) for item in event_rows]},
            "entities": {"count": len(entity_rows), "row_hashes": [sha256_json(item) for item in entity_rows]},
            "participant_bearing_events": {
                "count": len(participant_rows),
                "row_pks": [int(item["row_pk"]) for item in participant_rows if item.get("row_pk") is not None],
            },
        },
        "rollback_contract": row.get("rollback_contract") if isinstance(row.get("rollback_contract"), dict) else {},
        "postwrite_readback_contract": row.get("postwrite_readback_contract") if isinstance(row.get("postwrite_readback_contract"), dict) else {},
        "source_ref_readback_note": "source_ref_ids are preserved as report-only contract selectors; this source/raw DB schema stores article/event/entity lineage rather than a dedicated source_ref table.",
        "write_execution_allowed_now": False,
        "source_sqlite_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
    }
    snapshot["real_snapshot_row_sha256"] = sha256_json(snapshot)
    return snapshot, sorted(set(blockers))


def upstream_failures(summary: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    if compact(summary.get("decision")) != "atlas_social_manual_participant_source_raw_mapping_probe_ready_report_only":
        failures.append("upstream_mapping_probe_not_ready")
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    if int(counts.get("source_raw_mapping_ready_rows") or -1) != len(rows):
        failures.append("upstream_ready_row_count_mismatch")
    leaks = summary.get("leak_counts") if isinstance(summary.get("leak_counts"), dict) else {}
    if any(int(leaks.get(key) or 0) for key in ["public_url_hits", "sensitive_key_hits", "local_path_hits"]):
        failures.append("upstream_leak_counts_not_zero")
    return failures


def build_packet(mapping_rows_path: Path, mapping_summary_path: Path, target_db: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    generated_at = now_iso()
    rows = read_jsonl(mapping_rows_path, "mapping_rows")
    summary_in = read_json(mapping_summary_path)
    upstream = upstream_failures(summary_in, rows)
    target_db_display = display_path(target_db)

    row_contract_blocked: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    for row in rows:
        blockers = row_blockers(row)
        if blockers:
            row_contract_blocked.append(
                {
                    "schema_version": SCHEMA_VERSION + ".blocked_row",
                    "generated_at": generated_at,
                    "mapping_probe_id": compact(row.get("mapping_probe_id"), 180),
                    "candidate_lane": compact(row.get("candidate_lane"), 100),
                    "article_uid": compact(row.get("article_uid"), 260),
                    "blockers": blockers,
                    "write_execution_allowed_now": False,
                }
            )
        else:
            candidate_rows.append(row)

    snapshots: list[dict[str, Any]] = []
    db_blocked: list[dict[str, Any]] = []
    with open_readonly(target_db) as conn:
        for row in candidate_rows:
            snapshot, blockers = build_snapshot(conn, row, target_db_display, generated_at)
            if blockers:
                db_blocked.append(
                    {
                        "schema_version": SCHEMA_VERSION + ".blocked_row",
                        "generated_at": generated_at,
                        "mapping_probe_id": compact(row.get("mapping_probe_id"), 180),
                        "candidate_lane": compact(row.get("candidate_lane"), 100),
                        "article_uid": compact(row.get("article_uid"), 260),
                        "blockers": blockers,
                        "write_execution_allowed_now": False,
                    }
                )
            else:
                snapshots.append(snapshot)

    blocked = row_contract_blocked + db_blocked
    leak_counts = scan_payload(snapshots + blocked)
    duplicate_hashes = sorted(
        item for item, count in Counter(row["real_snapshot_row_sha256"] for row in snapshots).items() if count > 1
    )
    failed_checks = sorted(
        set(
            upstream
            + (["blocked_rows_present"] if blocked else [])
            + (["duplicate_real_snapshot_hashes"] if duplicate_hashes else [])
            + [key for key, value in leak_counts.items() if value]
        )
    )
    decision = (
        "atlas_mapped_source_raw_real_snapshot_gate_ready_report_only"
        if snapshots and not failed_checks
        else "atlas_mapped_source_raw_real_snapshot_gate_blocked_report_only"
    )
    lane_counts = Counter(row["candidate_lane"] for row in snapshots)
    counts = {
        "input_mapping_rows": len(rows),
        "candidate_rows_after_contract_checks": len(candidate_rows),
        "real_snapshot_rows": len(snapshots),
        "blocked_rows": len(blocked),
        "source_date_snapshot_rows": lane_counts.get("manual_date_context", 0),
        "overnight_midnight_snapshot_rows": lane_counts.get("overnight_midnight_boundary", 0),
        "remaining_identity_snapshot_rows": lane_counts.get("remaining_event_identity", 0),
        "target_db_opened_read_only": 1,
        "unique_articles": len({row["article_uid"] for row in snapshots}),
        "raw_event_rows_snapshotted": sum(row["target_db_rows"]["events"]["count"] for row in snapshots),
        "article_rows_snapshotted": sum(row["target_db_rows"]["articles"]["count"] for row in snapshots),
        "entity_rows_snapshotted": sum(row["target_db_rows"]["entities"]["count"] for row in snapshots),
        "participant_bearing_event_rows": sum(row["target_db_rows"]["participant_bearing_events"]["count"] for row in snapshots),
        "real_snapshot_hashes": len({row["real_snapshot_row_sha256"] for row in snapshots}),
        "duplicate_real_snapshot_hashes": len(duplicate_hashes),
        "accepted_for_graph_rows": 0,
        "source_sqlite_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
    }
    outputs = {
        "summary_json": display_path(out_dir / "mapped_source_raw_real_snapshot_gate_summary.json"),
        "summary_md": display_path(out_dir / "mapped_source_raw_real_snapshot_gate_summary.md"),
        "real_snapshot_rows": display_path(out_dir / "mapped_source_raw_real_snapshot_rows.jsonl"),
        "blocked_rows": display_path(out_dir / "mapped_source_raw_real_snapshot_blocked_rows.jsonl"),
        "report": display_path(report_path),
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "counts": counts,
        "leak_counts": leak_counts,
        "inputs": {
            "mapping_rows": display_path(mapping_rows_path),
            "mapping_summary": display_path(mapping_summary_path),
            "target_db": target_db_display,
        },
        "outputs": outputs,
        "upstream_failures": upstream,
        "duplicate_real_snapshot_hashes": duplicate_hashes,
        "boundary": {
            "report_only": True,
            "target_db_opened_read_only": True,
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
        "write_guards": {
            "write_execution_allowed_now": False,
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
        },
        "next_cursor": outputs["real_snapshot_rows"] if decision.endswith("_ready_report_only") else outputs["blocked_rows"],
        "next_gate": "future mapped source/raw writer must require confirm token, inverse rollback, postwrite readback, and a separate serving rebuild gate",
    }

    write_jsonl(out_dir / "mapped_source_raw_real_snapshot_rows.jsonl", snapshots)
    write_jsonl(out_dir / "mapped_source_raw_real_snapshot_blocked_rows.jsonl", blocked)
    write_json(out_dir / "mapped_source_raw_real_snapshot_gate_summary.json", summary)
    write_text(out_dir / "mapped_source_raw_real_snapshot_gate_summary.md", render_summary(summary))
    write_text(report_path, render_report(summary))
    return summary


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Atlas T5 Mapped Source/Raw Real Snapshot Gate Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Input/real/blocked rows: `{counts['input_mapping_rows']}/{counts['real_snapshot_rows']}/{counts['blocked_rows']}`",
            f"- Lane split source-date/midnight/remaining: `{counts['source_date_snapshot_rows']}/{counts['overnight_midnight_snapshot_rows']}/{counts['remaining_identity_snapshot_rows']}`",
            f"- Raw event/article/entity rows snapshotted: `{counts['raw_event_rows_snapshotted']}/{counts['article_rows_snapshotted']}/{counts['entity_rows_snapshotted']}`",
            f"- Target DB opened read-only: `{counts['target_db_opened_read_only']}`",
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
            "# Atlas T5 Mapped Source/Raw Real Snapshot Gate - 2026-05-26",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            "- Boundary: report-only read-only real snapshot. It opens the mapped explicit source/raw SQLite target in read-only mode and records article/raw event/entity row hashes. It does not execute source/raw DB writes, serving rebuild, graph/vector writes, public pointer changes, deploys, mini-program upload/review, model calls, credential reads, or memory writes.",
            "",
            "## Counts",
            "",
            f"- Input mapping rows / real snapshot rows / blocked rows: `{counts['input_mapping_rows']}/{counts['real_snapshot_rows']}/{counts['blocked_rows']}`",
            f"- Lane split source-date / overnight-midnight / remaining-identity: `{counts['source_date_snapshot_rows']}/{counts['overnight_midnight_snapshot_rows']}/{counts['remaining_identity_snapshot_rows']}`",
            f"- Unique articles: `{counts['unique_articles']}`",
            f"- Raw event / article / entity rows snapshotted: `{counts['raw_event_rows_snapshotted']}/{counts['article_rows_snapshotted']}/{counts['entity_rows_snapshotted']}`",
            f"- Participant-bearing raw event rows: `{counts['participant_bearing_event_rows']}`",
            f"- Real snapshot hashes / duplicate hashes: `{counts['real_snapshot_hashes']}/{counts['duplicate_real_snapshot_hashes']}`",
            "- Accepted/source-sqlite/serving/graph/public/memory rows: `0/0/0/0/0/0`",
            f"- Public URL / sensitive key / local path leak hits: `{leak['public_url_hits']}/{leak['sensitive_key_hits']}/{leak['local_path_hits']}`",
            "",
            "## Evidence",
            "",
            f"- Summary JSON: `{outputs['summary_json']}`",
            f"- Real snapshot rows: `{outputs['real_snapshot_rows']}`",
            f"- Blocked rows: `{outputs['blocked_rows']}`",
            "",
            "## Next Cursor",
            "",
            f"`{summary['next_cursor']}`",
            "",
            "A future writer still needs a separate confirm-token execution packet with rollback and postwrite readback. This packet is not mutation authorization.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping-rows", type=Path, default=DEFAULT_MAPPING_ROWS)
    parser.add_argument("--mapping-summary", type=Path, default=DEFAULT_MAPPING_SUMMARY)
    parser.add_argument(
        "--target-db",
        type=Path,
        default=REPO_ROOT
        / "reports"
        / "atlas_incremental_wechat_refresh_20260522_1438"
        / "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435"
        / "atlas.sqlite",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(args.mapping_rows, args.mapping_summary, args.target_db, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["decision"].endswith("_ready_report_only") else 1


if __name__ == "__main__":
    raise SystemExit(main())
