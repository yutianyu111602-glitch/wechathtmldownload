#!/usr/bin/env python3
"""Build a DB2 external-link projection prewrite packet from OpenClaw L5 output.

This is the production-candidate bridge after the DB2 external-link Docker
longrun. It dedupes report-only L5 merge candidates, records blockers and
duplicates, and emits dry-run DB2 writer spool contracts. It does not open or
mutate DB1/DB2/DB3.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"

SCHEMA_VERSION = "db2_external_link_projection_prewrite_packet.v1"
DEFAULT_LONGRUN_ROOT = REPORTS_ROOT / "openclaw_db2_external_link_longrun_20260604"
DEFAULT_OUT_DIR = REPORTS_ROOT / "db2_external_link_projection_prewrite_packet_20260604"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "DB2_EXTERNAL_LINK_PROJECTION_PREWRITE_PACKET_20260604.md"

MERGE_CANDIDATES_NAME = "openclaw-db2-outlink-sidecar-merge_sidecar_merge_candidates.jsonl"
MERGE_BLOCKERS_NAME = "openclaw-db2-outlink-sidecar-merge_sidecar_merge_blockers.jsonl"
OFFICIAL_BATCH_RE = re.compile(r"^batch_\d{3}_\d{3}$")
SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|api[_-]?key[\"']?\s*[:=]|authorization[\"']?\s*[:=]|"
    r"bearer\s+[A-Za-z0-9._-]+|cookie[\"']?\s*[:=]|password[\"']?\s*[:=]|"
    r"secret[\"']?\s*[:=]|token[\"']?\s*[:=]|BEGIN [A-Z ]*PRIVATE KEY)"
)
PRIVATE_PATH_RE = re.compile(
    r"(?i)([A-Z]:\\|\\\\wsl\.localhost\\|(?<![A-Za-z0-9._~:/-])(?:/home/|/Users/|/mnt/[cd]/))"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    atomic_write_text(path, text)


def stable_hash(value: Any, length: int = 24) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:length]


def text_value(value: Any, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_no}: expected JSON object")
        rows.append(value)
    return rows


def official_batch_dirs(longrun_root: Path) -> tuple[list[Path], list[str]]:
    if not longrun_root.exists():
        return [], []
    official: list[Path] = []
    ignored: list[str] = []
    for path in sorted(p for p in longrun_root.iterdir() if p.is_dir()):
        if OFFICIAL_BATCH_RE.match(path.name):
            official.append(path)
        else:
            ignored.append(path.name)
    return official, ignored


def load_l5_rows(longrun_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    official, ignored = official_batch_dirs(longrun_root)
    for batch_dir in official:
        candidate_path = batch_dir / MERGE_CANDIDATES_NAME
        blocker_path = batch_dir / MERGE_BLOCKERS_NAME
        for row in read_jsonl(candidate_path):
            row = dict(row)
            row["_source_batch"] = batch_dir.name
            row["_source_file"] = f"{batch_dir.name}/{MERGE_CANDIDATES_NAME}"
            rows.append(row)
        for row in read_jsonl(blocker_path):
            row = dict(row)
            row["_source_batch"] = batch_dir.name
            row["_source_file"] = f"{batch_dir.name}/{MERGE_BLOCKERS_NAME}"
            blockers.append(row)
    return rows, blockers, ignored


def is_ready_l5_candidate(row: dict[str, Any]) -> bool:
    return (
        row.get("merge_status") == "candidate"
        and row.get("fetch_status") == "fetched"
        and not row.get("db_write_allowed_now")
        and not row.get("db2_projection_allowed_now")
        and text_value(row.get("entity_search_id"), 120) != ""
        and text_value(row.get("source_url_hash"), 128) != ""
    )


def candidate_rank(row: dict[str, Any]) -> tuple[int, int, int, int, str, str]:
    return (
        int_value(row.get("confidence_score")),
        1 if text_value(row.get("metadata_title"), 200) else 0,
        1 if text_value(row.get("metadata_description"), 300) else 0,
        1 if int_value(row.get("http_status")) == 200 else 0,
        text_value(row.get("_source_batch"), 80),
        text_value(row.get("task_id"), 120),
    )


def projection_candidate_id(entity_search_id: str, source_url_hash: str) -> str:
    return "db2_external_link_projection:" + stable_hash(
        {"entity_search_id": entity_search_id, "source_url_hash": source_url_hash},
        24,
    )


def build_prewrite_candidate(row: dict[str, Any], duplicate_count: int) -> dict[str, Any]:
    entity_search_id = text_value(row.get("entity_search_id"), 120)
    source_url_hash = text_value(row.get("source_url_hash"), 128)
    candidate_id = projection_candidate_id(entity_search_id, source_url_hash)
    selector = {
        "entity_search_id": entity_search_id,
        "source_url_hash": source_url_hash,
    }
    return {
        "schema_version": SCHEMA_VERSION + ".candidate",
        "projection_candidate_id": candidate_id,
        "operation": "upsert_external_link_candidate",
        "dedupe_key": "entity_search_id+source_url_hash",
        "dedupe_key_hash": stable_hash(selector, 24),
        "merge_candidate_id": text_value(row.get("merge_candidate_id"), 120),
        "source_task_id": text_value(row.get("task_id"), 120),
        "entity_search_id": entity_search_id,
        "entity_name": text_value(row.get("entity_name"), 180),
        "entity_type": text_value(row.get("entity_type"), 80),
        "platform": text_value(row.get("platform"), 80),
        "public_category": text_value(row.get("public_category"), 80),
        "safe_url": text_value(row.get("safe_url"), 1200),
        "source_url_hash": source_url_hash,
        "http_status": int_value(row.get("http_status")),
        "fetch_status": text_value(row.get("fetch_status"), 80),
        "metadata_title": text_value(row.get("metadata_title"), 220),
        "metadata_description": text_value(row.get("metadata_description"), 360),
        "metadata_site": text_value(row.get("metadata_site"), 120),
        "confidence_score": int_value(row.get("confidence_score")),
        "confidence_band": text_value(row.get("confidence_band"), 80),
        "selected_from_batch": text_value(row.get("_source_batch"), 80),
        "selected_source_file": text_value(row.get("_source_file"), 260),
        "duplicate_evidence_count": duplicate_count,
        "projection_status": "prewrite_candidate_ready_report_only",
        "rollback_contract_status": "prewrite_snapshot_required_before_any_write",
        "postwrite_readback_required": True,
        "db2_projection_allowed_now": False,
        "db2_write_allowed_now": False,
        "write_execution_allowed_now": False,
        "live_db2_spool_delivery_allowed_now": False,
        "requires_explicit_confirm_token": True,
        "selector": selector,
    }


def build_duplicate_row(row: dict[str, Any], selected_id: str, duplicate_index: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".duplicate",
        "projection_candidate_id": selected_id,
        "duplicate_index": duplicate_index,
        "merge_candidate_id": text_value(row.get("merge_candidate_id"), 120),
        "source_task_id": text_value(row.get("task_id"), 120),
        "entity_search_id": text_value(row.get("entity_search_id"), 120),
        "entity_name": text_value(row.get("entity_name"), 180),
        "source_url_hash": text_value(row.get("source_url_hash"), 128),
        "safe_url": text_value(row.get("safe_url"), 1200),
        "confidence_score": int_value(row.get("confidence_score")),
        "metadata_title": text_value(row.get("metadata_title"), 220),
        "source_batch": text_value(row.get("_source_batch"), 80),
        "duplicate_disposition": "deduped_same_entity_same_url_report_only",
        "db2_write_allowed_now": False,
    }


def dedupe_ready_rows(ready_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in ready_rows:
        key = (text_value(row.get("entity_search_id"), 120), text_value(row.get("source_url_hash"), 128))
        groups.setdefault(key, []).append(row)

    candidates: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for key in sorted(groups):
        group = sorted(groups[key], key=candidate_rank, reverse=True)
        selected = group[0]
        candidate = build_prewrite_candidate(selected, max(len(group) - 1, 0))
        candidates.append(candidate)
        for index, duplicate in enumerate(group[1:], start=1):
            duplicates.append(build_duplicate_row(duplicate, candidate["projection_candidate_id"], index))
    return candidates, duplicates


def build_blocker_row(row: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".blocker",
        "source": source,
        "merge_candidate_id": text_value(row.get("merge_candidate_id"), 120),
        "source_task_id": text_value(row.get("task_id"), 120),
        "entity_search_id": text_value(row.get("entity_search_id"), 120),
        "entity_name": text_value(row.get("entity_name"), 180),
        "entity_type": text_value(row.get("entity_type"), 80),
        "platform": text_value(row.get("platform"), 80),
        "public_category": text_value(row.get("public_category"), 80),
        "safe_url": text_value(row.get("safe_url"), 1200),
        "source_url_hash": text_value(row.get("source_url_hash"), 128),
        "http_status": int_value(row.get("http_status")),
        "fetch_status": text_value(row.get("fetch_status"), 80),
        "blocked_reason": text_value(row.get("blocked_reason") or "not_ready_for_projection_prewrite", 240),
        "source_batch": text_value(row.get("_source_batch"), 80),
        "projection_status": "blocked_before_projection_prewrite",
        "db2_projection_allowed_now": False,
        "db2_write_allowed_now": False,
    }


def build_spool_event(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".dryrun_spool_event",
        "op": candidate["operation"],
        "mode": "dry_run_only",
        "projection_candidate_id": candidate["projection_candidate_id"],
        "entity_search_id": candidate["entity_search_id"],
        "entity_name": candidate["entity_name"],
        "entity_type": candidate["entity_type"],
        "platform": candidate["platform"],
        "public_category": candidate["public_category"],
        "safe_url": candidate["safe_url"],
        "source_url_hash": candidate["source_url_hash"],
        "metadata_title": candidate["metadata_title"],
        "metadata_description": candidate["metadata_description"],
        "metadata_site": candidate["metadata_site"],
        "confidence_score": candidate["confidence_score"],
        "confidence_band": candidate["confidence_band"],
        "selector": candidate["selector"],
        "db2_projection_allowed_now": False,
        "db2_write_allowed_now": False,
        "write_execution_allowed_now": False,
        "live_db2_spool_delivery_allowed_now": False,
    }


def build_rollback_contract(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".rollback_contract",
        "projection_candidate_id": candidate["projection_candidate_id"],
        "selector": candidate["selector"],
        "rollback_contract_status": "prewrite_snapshot_required_before_any_write",
        "rollback_action": "restore_prewrite_snapshot_or_delete_created_candidate",
        "prewrite_snapshot_required": True,
        "db2_write_allowed_now": False,
    }


def build_readback_contract(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".postwrite_readback_contract",
        "projection_candidate_id": candidate["projection_candidate_id"],
        "selector": candidate["selector"],
        "expected": {
            "entity_search_id": candidate["entity_search_id"],
            "source_url_hash": candidate["source_url_hash"],
            "safe_url": candidate["safe_url"],
            "platform": candidate["platform"],
            "public_category": candidate["public_category"],
            "projection_status": "projected_after_explicit_write_gate",
        },
        "postwrite_readback_required": True,
        "db2_write_allowed_now": False,
    }


def iter_string_values(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        values: list[str] = []
        for child in payload.values():
            values.extend(iter_string_values(child))
        return values
    if isinstance(payload, list):
        values = []
        for child in payload:
            values.extend(iter_string_values(child))
        return values
    if isinstance(payload, str):
        return [payload]
    return []


def leak_findings(payload: Any) -> list[dict[str, str]]:
    text = "\n".join(iter_string_values(payload))
    findings: list[dict[str, str]] = []
    for name, pattern in [("secret_like", SECRET_RE), ("private_local_path", PRIVATE_PATH_RE)]:
        for match in pattern.finditer(text):
            findings.append({"kind": name, "sample": match.group(0)[:48]})
            if len(findings) >= 20:
                return findings
    return findings


def atomic_replace_sqlite(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(suffix=".sqlite", dir=path.parent)
    os.close(fd)
    conn = sqlite3.connect(temp_name)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA user_version=260604")
    conn.execute("CREATE TABLE __target_path(path TEXT NOT NULL)")
    conn.execute("INSERT INTO __target_path VALUES (?)", (str(path),))
    return conn


def finish_sqlite(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT path FROM __target_path").fetchone()
    target = Path(row[0])
    temp_name = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    conn.execute("DROP TABLE __target_path")
    conn.commit()
    conn.close()
    os.replace(temp_name, target)


def write_sqlite(path: Path, candidates: list[dict[str, Any]], duplicates: list[dict[str, Any]], blockers: list[dict[str, Any]]) -> dict[str, int]:
    conn = atomic_replace_sqlite(path)
    conn.executescript(
        """
        CREATE TABLE external_link_projection_prewrite_candidates (
          projection_candidate_id TEXT PRIMARY KEY,
          entity_search_id TEXT NOT NULL,
          entity_name TEXT NOT NULL,
          entity_type TEXT NOT NULL,
          platform TEXT NOT NULL,
          public_category TEXT NOT NULL,
          safe_url TEXT NOT NULL,
          source_url_hash TEXT NOT NULL,
          metadata_title TEXT NOT NULL,
          metadata_description TEXT NOT NULL,
          metadata_site TEXT NOT NULL,
          confidence_score INTEGER NOT NULL,
          confidence_band TEXT NOT NULL,
          selected_from_batch TEXT NOT NULL,
          duplicate_evidence_count INTEGER NOT NULL,
          db2_write_allowed_now INTEGER NOT NULL,
          write_execution_allowed_now INTEGER NOT NULL
        );
        CREATE TABLE external_link_projection_prewrite_duplicates (
          projection_candidate_id TEXT NOT NULL,
          duplicate_index INTEGER NOT NULL,
          merge_candidate_id TEXT NOT NULL,
          source_task_id TEXT NOT NULL,
          source_batch TEXT NOT NULL,
          duplicate_disposition TEXT NOT NULL
        );
        CREATE TABLE external_link_projection_prewrite_blockers (
          merge_candidate_id TEXT NOT NULL,
          entity_search_id TEXT NOT NULL,
          entity_name TEXT NOT NULL,
          platform TEXT NOT NULL,
          blocked_reason TEXT NOT NULL,
          source_batch TEXT NOT NULL
        );
        CREATE INDEX idx_db2_ext_prewrite_entity ON external_link_projection_prewrite_candidates(entity_search_id);
        CREATE INDEX idx_db2_ext_prewrite_platform ON external_link_projection_prewrite_candidates(platform, public_category);
        CREATE INDEX idx_db2_ext_prewrite_url_hash ON external_link_projection_prewrite_candidates(source_url_hash);
        """
    )
    conn.executemany(
        """
        INSERT INTO external_link_projection_prewrite_candidates VALUES (
          :projection_candidate_id, :entity_search_id, :entity_name, :entity_type,
          :platform, :public_category, :safe_url, :source_url_hash, :metadata_title,
          :metadata_description, :metadata_site, :confidence_score, :confidence_band,
          :selected_from_batch, :duplicate_evidence_count, :db2_write_allowed_now,
          :write_execution_allowed_now
        )
        """,
        [
            {
                **row,
                "db2_write_allowed_now": int(bool(row["db2_write_allowed_now"])),
                "write_execution_allowed_now": int(bool(row["write_execution_allowed_now"])),
            }
            for row in candidates
        ],
    )
    conn.executemany(
        """
        INSERT INTO external_link_projection_prewrite_duplicates VALUES (
          :projection_candidate_id, :duplicate_index, :merge_candidate_id,
          :source_task_id, :source_batch, :duplicate_disposition
        )
        """,
        duplicates,
    )
    conn.executemany(
        """
        INSERT INTO external_link_projection_prewrite_blockers VALUES (
          :merge_candidate_id, :entity_search_id, :entity_name, :platform,
          :blocked_reason, :source_batch
        )
        """,
        blockers,
    )
    readback = {
        "candidate_rows": int(conn.execute("SELECT COUNT(*) FROM external_link_projection_prewrite_candidates").fetchone()[0]),
        "duplicate_rows": int(conn.execute("SELECT COUNT(*) FROM external_link_projection_prewrite_duplicates").fetchone()[0]),
        "blocker_rows": int(conn.execute("SELECT COUNT(*) FROM external_link_projection_prewrite_blockers").fetchone()[0]),
        "write_allowed_rows": int(
            conn.execute(
                "SELECT COUNT(*) FROM external_link_projection_prewrite_candidates "
                "WHERE db2_write_allowed_now != 0 OR write_execution_allowed_now != 0"
            ).fetchone()[0]
        ),
    }
    finish_sqlite(conn)
    return readback


def render_scorecard(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# DB2 External Link Projection Prewrite Packet 20260604",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Official batches: `{summary['official_batch_count']}`",
        f"- L5 result rows: `{summary['input_l5_result_rows']}`",
        f"- Ready L5 candidates: `{summary['ready_l5_candidate_rows']}`",
        f"- Unique prewrite candidates: `{summary['unique_prewrite_candidate_rows']}`",
        f"- Duplicate evidence rows: `{summary['duplicate_evidence_rows']}`",
        f"- Blocked rows: `{summary['blocked_rows']}`",
        f"- Leak findings: `{summary['leak_finding_count']}`",
        f"- DB2 write allowed rows: `{summary['db2_write_allowed_rows']}`",
        "",
        "## Artifacts",
        "",
    ]
    for key, value in report["artifacts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Report-local production candidate package only.",
            "- No DB1/DB2/DB3 mutation, no live DB2 spool delivery, no DB2 projection execution.",
            "- Future write still requires explicit confirm token, prewrite snapshot, write lock/lease, rollback, and postwrite readback.",
            "",
            "## Platform Counts",
            "",
        ]
    )
    for key, value in sorted(summary["prewrite_by_platform"].items()):
        lines.append(f"- `{key}`: `{value}`")
    return "\n".join(lines) + "\n"


def build_packet(*, longrun_root: Path, out_dir: Path, scorecard_path: Path) -> dict[str, Any]:
    generated_at = now_iso()
    l5_rows, l5_blocker_rows, ignored_dirs = load_l5_rows(longrun_root)
    ready_rows = [row for row in l5_rows if is_ready_l5_candidate(row)]
    not_ready_rows = [row for row in l5_rows if not is_ready_l5_candidate(row)]
    candidates, duplicates = dedupe_ready_rows(ready_rows)
    blockers = [build_blocker_row(row, "l5_result_row") for row in not_ready_rows]
    blocker_ids = {row.get("merge_candidate_id") for row in blockers}
    for row in l5_blocker_rows:
        if row.get("merge_candidate_id") not in blocker_ids:
            blockers.append(build_blocker_row(row, "l5_blocker_file"))

    spool_events = [build_spool_event(row) for row in candidates]
    rollback_contracts = [build_rollback_contract(row) for row in candidates]
    readback_contracts = [build_readback_contract(row) for row in candidates]
    findings = leak_findings(
        {
            "candidates": candidates,
            "duplicates": duplicates,
            "blockers": blockers,
            "spool_events": spool_events,
            "rollback_contracts": rollback_contracts,
            "readback_contracts": readback_contracts,
        }
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = out_dir / "db2_external_link_projection_prewrite_candidates.jsonl"
    duplicates_path = out_dir / "db2_external_link_projection_duplicate_evidence.jsonl"
    blockers_path = out_dir / "db2_external_link_projection_blockers.jsonl"
    spool_path = out_dir / "db2_writer_dryrun_spool" / "incoming" / "db2_external_link_projection_prewrite_events.jsonl"
    rollback_path = out_dir / "db2_external_link_projection_rollback_contracts.jsonl"
    readback_path = out_dir / "db2_external_link_projection_postwrite_readback_contracts.jsonl"
    sqlite_path = out_dir / "db2_external_link_projection_prewrite.sqlite"
    report_path = out_dir / "db2_external_link_projection_prewrite_packet.json"

    write_jsonl(candidates_path, candidates)
    write_jsonl(duplicates_path, duplicates)
    write_jsonl(blockers_path, blockers)
    write_jsonl(spool_path, spool_events)
    write_jsonl(rollback_path, rollback_contracts)
    write_jsonl(readback_path, readback_contracts)
    sqlite_readback = write_sqlite(sqlite_path, candidates, duplicates, blockers)

    official, _ = official_batch_dirs(longrun_root)
    summary = {
        "official_batch_count": len(official),
        "ignored_diagnostic_dirs": ignored_dirs,
        "input_l5_result_rows": len(l5_rows),
        "input_l5_blocker_file_rows": len(l5_blocker_rows),
        "ready_l5_candidate_rows": len(ready_rows),
        "unique_prewrite_candidate_rows": len(candidates),
        "duplicate_evidence_rows": len(duplicates),
        "blocked_rows": len(blockers),
        "spool_event_rows": len(spool_events),
        "rollback_contract_rows": len(rollback_contracts),
        "postwrite_readback_contract_rows": len(readback_contracts),
        "prewrite_by_platform": dict(Counter(row["platform"] for row in candidates).most_common()),
        "prewrite_by_entity_type": dict(Counter(row["entity_type"] for row in candidates).most_common()),
        "blockers_by_reason": dict(Counter(row["blocked_reason"] for row in blockers).most_common()),
        "leak_finding_count": len(findings),
        "db2_write_allowed_rows": sum(1 for row in candidates if row["db2_write_allowed_now"] or row["write_execution_allowed_now"]),
        "live_db2_spool_delivery_allowed_rows": sum(1 for row in candidates if row["live_db2_spool_delivery_allowed_now"]),
        "sqlite_readback": sqlite_readback,
    }
    decision = (
        "db2_external_link_projection_prewrite_packet_ready_report_only"
        if candidates
        and not findings
        and summary["db2_write_allowed_rows"] == 0
        and summary["live_db2_spool_delivery_allowed_rows"] == 0
        and sqlite_readback["candidate_rows"] == len(candidates)
        and sqlite_readback["write_allowed_rows"] == 0
        else "db2_external_link_projection_prewrite_packet_blocked_report_only"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "decision": decision,
        "inputs": {
            "longrun_root": rel_path(longrun_root),
            "official_batch_glob": "batch_###_###",
        },
        "artifacts": {
            "report_json": rel_path(report_path),
            "scorecard": rel_path(scorecard_path),
            "prewrite_candidates_jsonl": rel_path(candidates_path),
            "duplicate_evidence_jsonl": rel_path(duplicates_path),
            "blockers_jsonl": rel_path(blockers_path),
            "dryrun_spool_incoming_jsonl": rel_path(spool_path),
            "rollback_contracts_jsonl": rel_path(rollback_path),
            "postwrite_readback_contracts_jsonl": rel_path(readback_path),
            "report_local_sqlite": rel_path(sqlite_path),
        },
        "summary": summary,
        "safety": {
            "report_only": True,
            "db1_mutation": False,
            "db2_mutation": False,
            "db3_mutation": False,
            "db2_projection_executed": False,
            "live_db2_spool_delivery": False,
            "network_fetch": False,
            "cookie_token_secret_read": False,
            "secret_values_printed": False,
            "leak_findings": findings,
        },
        "next_gate": {
            "name": "explicit_db2_projection_execution_gate",
            "requires_confirm_token": True,
            "requires_single_writer_lock": True,
            "requires_prewrite_snapshot": True,
            "requires_rollback_contract": True,
            "requires_postwrite_readback": True,
            "execute_allowed_now": False,
        },
    }
    write_json(report_path, report)
    atomic_write_text(scorecard_path, render_scorecard(report))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--longrun-root", type=Path, default=DEFAULT_LONGRUN_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_packet(longrun_root=args.longrun_root, out_dir=args.out_dir, scorecard_path=args.scorecard)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "summary": report["summary"],
                "artifacts": report["artifacts"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["decision"] == "db2_external_link_projection_prewrite_packet_ready_report_only" else 1


if __name__ == "__main__":
    raise SystemExit(main())
