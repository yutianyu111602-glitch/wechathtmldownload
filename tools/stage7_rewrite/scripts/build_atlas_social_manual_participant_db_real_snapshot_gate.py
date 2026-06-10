#!/usr/bin/env python3
"""Build a report-only real DB snapshot gate for manual participant consolidation.

The script never writes to SQLite. Without an explicit --target-db it emits a
blocked packet that records why the prewrite snapshot cannot advance. With an
explicit target DB it opens the DB in SQLite read-only mode, captures row hashes
for the selected event/source rows, and still keeps write_execution_allowed_now
false for the next gate.
"""
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
DEFAULT_SNAPSHOT_ROWS = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_db_prewrite_snapshot_q6_20260526"
    / "manual_participant_db_prewrite_snapshot_rows.jsonl"
)
DEFAULT_PREWRITE_SUMMARY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_db_prewrite_snapshot_q6_20260526"
    / "manual_participant_db_prewrite_snapshot_summary.json"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_db_real_snapshot_gate_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_DB_REAL_SNAPSHOT_GATE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_db_real_snapshot_gate.v1"

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
        raise ValueError(f"{label} must not point to D: for manual participant real snapshot gate: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def list_strings(value: Any, limit: int = 180) -> list[str]:
    if not isinstance(value, list):
        return []
    return [compact(item, limit) for item in value if compact(item, limit)]


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


def scan_payload(payload: Any) -> dict[str, int]:
    text = canonical_json(payload)
    return {
        "public_url_hits": len(URL_RE.findall(text)),
        "sensitive_key_hits": len(SECRET_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
    }


def open_readonly(path: Path) -> sqlite3.Connection:
    reject_d_path(path, "target_db")
    if not path.exists():
        raise FileNotFoundError(path)
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    if not table_exists(conn, table):
        return []
    return [compact(row["name"], 160) for row in conn.execute(f'PRAGMA table_info("{table}")')]


def rowdict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def query_in(conn: sqlite3.Connection, sql_prefix: str, values: list[str], sql_suffix: str = "") -> list[dict[str, Any]]:
    if not values:
        return []
    placeholders = ",".join("?" for _ in values)
    return [rowdict(row) for row in conn.execute(f"{sql_prefix} ({placeholders}) {sql_suffix}", values)]


def event_ids(row: dict[str, Any]) -> list[str]:
    scope = dict_value(row.get("snapshot_scope"))
    return list_strings(scope.get("original_event_ids"))


def source_refs(row: dict[str, Any]) -> list[str]:
    scope = dict_value(row.get("snapshot_scope"))
    return list_strings(scope.get("source_ref_ids"))


def representative(row: dict[str, Any]) -> str:
    return compact(dict_value(row.get("snapshot_scope")).get("representative_event_id"), 180)


def row_blockers(row: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    ids = event_ids(row)
    refs = source_refs(row)
    rep = representative(row)
    if compact(row.get("snapshot_status")) != "manual_participant_db_prewrite_snapshot_materialized_report_only":
        blockers.append("snapshot_status_not_materialized")
    if row.get("write_execution_allowed_now") is not False:
        blockers.append("write_execution_allowed_now_not_false")
    if row.get("source_sqlite_write_allowed") is not False:
        blockers.append("source_sqlite_write_allowed_not_false")
    if row.get("serving_rebuild_allowed") is not False:
        blockers.append("serving_rebuild_allowed_not_false")
    if row.get("graph_write_allowed") is not False:
        blockers.append("graph_write_allowed_not_false")
    if row.get("public_serving_field_allowed") is not False:
        blockers.append("public_serving_field_allowed_not_false")
    if row.get("memory_write_allowed") is not False:
        blockers.append("memory_write_allowed_not_false")
    if not compact(row.get("contract_row_sha256"), 100):
        blockers.append("contract_row_sha256_missing")
    if not ids:
        blockers.append("original_event_ids_missing")
    if len(ids) < 2:
        blockers.append("needs_multiple_event_ids")
    if not rep:
        blockers.append("representative_event_id_missing")
    elif rep not in set(ids):
        blockers.append("representative_not_in_original_event_ids")
    if not refs:
        blockers.append("source_ref_ids_missing")
    work_order = dict_value(row.get("dry_run_prewrite_work_order"))
    if work_order.get("requires_explicit_target_db") is not True:
        blockers.append("requires_explicit_target_db_not_true")
    if work_order.get("execution_allowed_now") is not False:
        blockers.append("dry_run_execution_allowed_now_not_false")
    return sorted(set(blockers))


def fetch_snapshot(conn: sqlite3.Connection, row: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    ids = event_ids(row)
    refs = source_refs(row)
    blockers: list[str] = []
    tables = {
        "performance_event": table_exists(conn, "performance_event"),
        "dj_event": table_exists(conn, "dj_event"),
        "evidence_ref": table_exists(conn, "evidence_ref"),
        "event_identity_lineage": table_exists(conn, "event_identity_lineage"),
    }
    for required in ["performance_event", "dj_event", "evidence_ref"]:
        if not tables[required]:
            blockers.append(f"{required}_table_missing")

    performance_rows = []
    participant_rows = []
    evidence_rows = []
    lineage_rows = []
    if tables["performance_event"]:
        performance_rows = query_in(
            conn,
            """
            SELECT *
            FROM performance_event
            WHERE event_id IN
            """,
            ids,
            "ORDER BY event_id",
        )
        found = {compact(row.get("event_id"), 180) for row in performance_rows}
        missing = sorted(set(ids) - found)
        if missing:
            blockers.append("performance_event_rows_missing")
    if tables["dj_event"]:
        participant_rows = query_in(
            conn,
            """
            SELECT *
            FROM dj_event
            WHERE event_id IN
            """,
            ids,
            "ORDER BY event_id, dj_id, source_ref_id",
        )
        by_event = Counter(compact(row.get("event_id"), 180) for row in participant_rows)
        if any(by_event[event_id] <= 0 for event_id in ids):
            blockers.append("dj_event_participant_rows_missing")
    if tables["evidence_ref"]:
        evidence_rows = query_in(
            conn,
            """
            SELECT *
            FROM evidence_ref
            WHERE source_ref_id IN
            """,
            refs,
            "ORDER BY source_ref_id",
        )
        found_refs = {compact(row.get("source_ref_id"), 180) for row in evidence_rows}
        missing_refs = sorted(set(refs) - found_refs)
        if missing_refs:
            blockers.append("evidence_ref_rows_missing")
    if tables["event_identity_lineage"]:
        columns = table_columns(conn, "event_identity_lineage")
        if "event_id" in columns:
            lineage_rows = query_in(
                conn,
                """
                SELECT *
                FROM event_identity_lineage
                WHERE event_id IN
                """,
                ids,
                "ORDER BY event_id",
            )

    snapshot = {
        "schema_version": SCHEMA_VERSION + ".real_snapshot",
        "contract_row_sha256": compact(row.get("contract_row_sha256"), 100),
        "selector_hash": compact(row.get("selector_hash"), 100),
        "review_lane": compact(row.get("review_lane"), 100),
        "source_account": compact(row.get("source_account"), 220),
        "snapshot_scope": dict_value(row.get("snapshot_scope")),
        "target_db_rows": {
            "performance_event": {
                "count": len(performance_rows),
                "row_hashes": [sha256_json(item) for item in performance_rows],
            },
            "dj_event": {
                "count": len(participant_rows),
                "row_hashes": [sha256_json(item) for item in participant_rows],
                "count_by_event": dict(sorted(Counter(compact(item.get("event_id"), 180) for item in participant_rows).items())),
            },
            "evidence_ref": {
                "count": len(evidence_rows),
                "row_hashes": [sha256_json(item) for item in evidence_rows],
            },
            "event_identity_lineage": {
                "table_present": tables["event_identity_lineage"],
                "count": len(lineage_rows),
                "row_hashes": [sha256_json(item) for item in lineage_rows],
            },
        },
        "rollback_requirements": {
            "inverse_mapping_required": True,
            "representative_event_id": representative(row),
            "non_representative_event_ids": [
                event_id for event_id in event_ids(row) if event_id != representative(row)
            ],
            "must_preserve_prewrite_row_hashes": True,
        },
        "postwrite_verification_requirements": {
            "must_reopen_target_db_read_only": True,
            "must_verify_event_identity_lineage": True,
            "must_verify_participant_counts_not_lost": True,
            "must_verify_source_refs_still_resolve": True,
            "must_keep_public_and_serving_writes_separate": True,
        },
        "write_execution_allowed_now": False,
        "source_sqlite_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
    }
    snapshot["real_snapshot_row_sha256"] = sha256_json(snapshot)
    return snapshot, sorted(set(blockers))


def upstream_failures(summary: dict[str, Any], snapshot_rows: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    if compact(summary.get("decision")) != "atlas_social_manual_participant_db_prewrite_snapshot_ready_report_only":
        failures.append("upstream_prewrite_snapshot_not_ready")
    counts = dict_value(summary.get("counts"))
    try:
        expected = int(counts.get("prewrite_snapshot_rows"))
    except (TypeError, ValueError):
        expected = -1
    if expected != len(snapshot_rows):
        failures.append("upstream_snapshot_row_count_mismatch")
    for key, value in dict_value(summary.get("leak_counts")).items():
        if value:
            failures.append(f"upstream_leak_{key}")
    return failures


def build_packet(
    snapshot_rows_path: Path,
    prewrite_summary_path: Path,
    out_dir: Path,
    report_path: Path,
    target_db: Path | None = None,
) -> dict[str, Any]:
    generated_at = now_iso()
    rows = read_jsonl(snapshot_rows_path, "snapshot_rows")
    summary_in = read_json(prewrite_summary_path)
    upstream = upstream_failures(summary_in, rows)

    row_blocked: list[dict[str, Any]] = []
    candidate_rows = []
    for row in rows:
        blockers = row_blockers(row)
        if blockers:
            row_blocked.append(
                {
                    "schema_version": SCHEMA_VERSION + ".blocked_row",
                    "generated_at": generated_at,
                    "contract_row_sha256": compact(row.get("contract_row_sha256"), 100),
                    "selector_hash": compact(row.get("selector_hash"), 100),
                    "blockers": blockers,
                    "write_execution_allowed_now": False,
                }
            )
        else:
            candidate_rows.append(row)

    real_snapshots: list[dict[str, Any]] = []
    db_blocked: list[dict[str, Any]] = []
    target_db_opened = False
    target_db_display = None
    if target_db is None:
        for row in candidate_rows:
            db_blocked.append(
                {
                    "schema_version": SCHEMA_VERSION + ".blocked_row",
                    "generated_at": generated_at,
                    "contract_row_sha256": compact(row.get("contract_row_sha256"), 100),
                    "selector_hash": compact(row.get("selector_hash"), 100),
                    "blockers": ["explicit_target_db_missing"],
                    "required_arg": "--target-db",
                    "write_execution_allowed_now": False,
                }
            )
    else:
        reject_d_path(target_db, "target_db")
        target_db_display = display_path(target_db)
        with open_readonly(target_db) as conn:
            target_db_opened = True
            for row in candidate_rows:
                real_snapshot, blockers = fetch_snapshot(conn, row)
                real_snapshot["generated_at"] = generated_at
                real_snapshot["target_db"] = target_db_display
                if blockers:
                    db_blocked.append(
                        {
                            "schema_version": SCHEMA_VERSION + ".blocked_row",
                            "generated_at": generated_at,
                            "contract_row_sha256": compact(row.get("contract_row_sha256"), 100),
                            "selector_hash": compact(row.get("selector_hash"), 100),
                            "blockers": blockers,
                            "write_execution_allowed_now": False,
                        }
                    )
                else:
                    real_snapshots.append(real_snapshot)

    all_blocked = row_blocked + db_blocked
    leak_counts = scan_payload(real_snapshots + all_blocked)
    duplicate_hashes = sorted(
        item
        for item, count in Counter(row["real_snapshot_row_sha256"] for row in real_snapshots).items()
        if count > 1
    )
    failed_checks = sorted(
        set(
            upstream
            + (["blocked_rows_present"] if all_blocked else [])
            + (["duplicate_real_snapshot_hashes"] if duplicate_hashes else [])
            + [key for key, value in leak_counts.items() if value]
        )
    )
    decision = (
        "atlas_social_manual_participant_db_real_snapshot_gate_ready_report_only"
        if real_snapshots and not failed_checks
        else "atlas_social_manual_participant_db_real_snapshot_gate_blocked_report_only"
    )

    counts = {
        "input_prewrite_snapshot_rows": len(rows),
        "candidate_rows_after_contract_checks": len(candidate_rows),
        "real_snapshot_rows": len(real_snapshots),
        "blocked_rows": len(all_blocked),
        "explicit_target_db_present": 1 if target_db is not None else 0,
        "target_db_opened_read_only": 1 if target_db_opened else 0,
        "event_id_snapshot_rows": sum(1 for row in real_snapshots if row.get("review_lane") == "event_id_dedupe"),
        "semantic_cluster_snapshot_rows": sum(
            1 for row in real_snapshots if row.get("review_lane") == "semantic_event_cluster"
        ),
        "real_snapshot_hashes": len({row["real_snapshot_row_sha256"] for row in real_snapshots}),
        "duplicate_real_snapshot_hashes": len(duplicate_hashes),
        "accepted_for_graph_rows": 0,
        "source_sqlite_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
    }
    outputs = {
        "summary_json": display_path(out_dir / "manual_participant_db_real_snapshot_gate_summary.json"),
        "summary_md": display_path(out_dir / "manual_participant_db_real_snapshot_gate_summary.md"),
        "real_snapshot_rows": display_path(out_dir / "manual_participant_db_real_snapshot_rows.jsonl"),
        "blocked_rows": display_path(out_dir / "manual_participant_db_real_snapshot_blocked_rows.jsonl"),
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
            "prewrite_snapshot_rows": display_path(snapshot_rows_path),
            "prewrite_snapshot_summary": display_path(prewrite_summary_path),
            "target_db": target_db_display,
        },
        "outputs": outputs,
        "upstream_failures": upstream,
        "duplicate_real_snapshot_hashes": duplicate_hashes,
        "boundary": {
            "report_only": True,
            "target_db_opened_read_only": target_db_opened,
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
        "next_gate": (
            "provide an explicit --target-db and rerun read-only real snapshot gate"
            if target_db is None
            else "future separate write gate must require confirm token, rollback, and postwrite readback"
        ),
    }

    write_jsonl(out_dir / "manual_participant_db_real_snapshot_rows.jsonl", real_snapshots)
    write_jsonl(out_dir / "manual_participant_db_real_snapshot_blocked_rows.jsonl", all_blocked)
    write_json(out_dir / "manual_participant_db_real_snapshot_gate_summary.json", summary)
    write_text(out_dir / "manual_participant_db_real_snapshot_gate_summary.md", render_summary(summary))
    write_text(report_path, render_report(summary))
    return summary


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Atlas T6 Manual Participant DB Real Snapshot Gate Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Input prewrite rows: `{counts['input_prewrite_snapshot_rows']}`",
            f"- Real snapshot rows: `{counts['real_snapshot_rows']}`",
            f"- Blocked rows: `{counts['blocked_rows']}`",
            f"- Explicit target DB present/opened read-only: `{counts['explicit_target_db_present']}/{counts['target_db_opened_read_only']}`",
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
            "# Atlas T6 Manual Participant DB Real Snapshot Gate - 2026-05-26",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            "- Boundary: report-only real-snapshot gate. It requires an explicit target DB. Without one it blocks; with one it opens SQLite in read-only mode only and records row hashes. It does not execute source DB, serving SQLite, graph/vector, public, deploy, upload/review, or memory writes.",
            "",
            "## Counts",
            "",
            f"- Input prewrite snapshot rows: `{counts['input_prewrite_snapshot_rows']}`",
            f"- Candidate rows after contract checks: `{counts['candidate_rows_after_contract_checks']}`",
            f"- Real snapshot rows: `{counts['real_snapshot_rows']}`",
            f"- Blocked rows: `{counts['blocked_rows']}`",
            f"- Explicit target DB present / opened read-only: `{counts['explicit_target_db_present']}/{counts['target_db_opened_read_only']}`",
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
            "A future writer still needs a separate explicit write gate with confirm token, rollback evidence, and postwrite readback. This packet is not mutation authorization.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-rows", type=Path, default=DEFAULT_SNAPSHOT_ROWS)
    parser.add_argument("--prewrite-summary", type=Path, default=DEFAULT_PREWRITE_SUMMARY)
    parser.add_argument("--target-db", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(args.snapshot_rows, args.prewrite_summary, args.out_dir, args.report, args.target_db)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["decision"].endswith("_ready_report_only") else 1


if __name__ == "__main__":
    raise SystemExit(main())
