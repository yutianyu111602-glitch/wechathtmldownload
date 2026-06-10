#!/usr/bin/env python3
"""Materialize DB3 old-DJ-ID to canonical-DJ-ID redirects after identity merges."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.scripts import run_atlas_relation_identity_db3_canary_s148 as s148


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S157"
SCHEMA_VERSION = "atlas_identity_redirect_db3_write_s157.v1"

DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_identity_redirect_db3_write_s157_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_IDENTITY_REDIRECT_DB3_WRITE_S157_20260602.md"
DEFAULT_SOURCE_REPORTS = [
    REPORTS_ROOT / "atlas_relation_identity_db3_canary_s148_20260602" / "atlas_relation_identity_db3_canary_s148.json",
    REPORTS_ROOT / "atlas_relation_identity_db3_canary_s150_20260602" / "atlas_relation_identity_db3_canary_s150.json",
    REPORTS_ROOT / "atlas_relation_identity_db3_canary_s152_20260602" / "atlas_relation_identity_db3_canary_s152.json",
    REPORTS_ROOT / "atlas_relation_identity_db3_canary_s154_20260602" / "atlas_relation_identity_db3_canary_s154.json",
    REPORTS_ROOT / "atlas_relation_identity_db3_autobatch_s156_20260602" / "atlas_relation_identity_db3_autobatch_s156.json",
    REPORTS_ROOT / "atlas_relation_identity_db3_autobatch_s156b_20260602" / "atlas_relation_identity_db3_autobatch_s156.json",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object JSON: {path}")
    return value


def committed(payload: dict[str, Any]) -> bool:
    execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
    write_state = payload.get("write_state") if isinstance(payload.get("write_state"), dict) else {}
    return bool(execution.get("committed") or write_state.get("committed"))


def selected_rows_from_report(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    report_sha = s148.sha256_file(path)
    rows: list[dict[str, Any]] = []
    if isinstance(payload.get("selected_canary"), dict) and committed(payload):
        selected = payload["selected_canary"]
        rows.append(
            {
                "source_story_id": str(payload.get("current_story_id") or path.parent.name),
                "source_report_path": rel_path(path),
                "source_report_sha256": report_sha,
                "group_id": str(selected.get("group_id") or ""),
                "canonical_dj_id": str(selected.get("canonical_dj_id") or ""),
                "merge_dj_ids": [str(value) for value in selected.get("merge_dj_ids") or [] if str(value)],
            }
        )
    for iteration in payload.get("iterations") or []:
        if not (iteration.get("execution") or {}).get("committed"):
            continue
        rows.append(
            {
                "source_story_id": str(iteration.get("story_label") or payload.get("current_story_id") or path.parent.name).upper(),
                "source_report_path": rel_path(path),
                "source_report_sha256": report_sha,
                "group_id": str(iteration.get("selected_group_id") or ""),
                "canonical_dj_id": str(iteration.get("canonical_dj_id") or ""),
                "merge_dj_ids": [str(value) for value in iteration.get("merge_dj_ids") or [] if str(value)],
            }
        )
    return rows


def collect_redirect_rows(paths: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    redirects: list[dict[str, Any]] = []
    source_reports: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            source_reports.append({"path": rel_path(path), "exists": False})
            continue
        source_reports.append({"path": rel_path(path), "exists": True, "sha256": s148.sha256_file(path)})
        for selected in selected_rows_from_report(path):
            for old_id in selected["merge_dj_ids"]:
                redirects.append(
                    {
                        "old_dj_id": old_id,
                        "canonical_dj_id": selected["canonical_dj_id"],
                        "group_id": selected["group_id"],
                        "source_story_id": selected["source_story_id"],
                        "source_report_path": selected["source_report_path"],
                        "source_report_sha256": selected["source_report_sha256"],
                        "redirect_kind": "db3_identity_merge",
                    }
                )
    return redirects, source_reports


def dedupe_redirect_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_old: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for row in rows:
        old_id = row["old_dj_id"]
        existing = by_old.get(old_id)
        if existing and existing["canonical_dj_id"] != row["canonical_dj_id"]:
            conflicts.append({"old_dj_id": old_id, "first": existing, "second": row})
            continue
        by_old[old_id] = row
    return list(by_old.values()), conflicts


def old_reference_counts(conn: sqlite3.Connection, old_ids: list[str]) -> dict[str, int]:
    if not old_ids:
        return {
            "dj_profile": 0,
            "subject": 0,
            "dj_event": 0,
            "dj_venue": 0,
            "dj_collaborator": 0,
        }
    ph = ",".join("?" for _ in old_ids)
    return {
        "dj_profile": int(conn.execute(f"SELECT COUNT(*) FROM dj_profile WHERE dj_id IN ({ph})", old_ids).fetchone()[0]),
        "subject": int(conn.execute(f"SELECT COUNT(*) FROM subject WHERE subject_id IN ({ph})", old_ids).fetchone()[0]),
        "dj_event": int(conn.execute(f"SELECT COUNT(*) FROM dj_event WHERE dj_id IN ({ph})", old_ids).fetchone()[0]),
        "dj_venue": int(conn.execute(f"SELECT COUNT(*) FROM dj_venue WHERE dj_id IN ({ph})", old_ids).fetchone()[0]),
        "dj_collaborator": int(
            conn.execute(
                f"SELECT COUNT(*) FROM dj_collaborator WHERE src_dj_id IN ({ph}) OR dst_dj_id IN ({ph})",
                old_ids + old_ids,
            ).fetchone()[0]
        ),
    }


def validate_rows(conn: sqlite3.Connection, rows: list[dict[str, Any]], conflicts: list[dict[str, Any]]) -> list[str]:
    blockers: list[str] = []
    if conflicts:
        blockers.append("conflicting_old_to_canonical_redirects")
    if not rows:
        blockers.append("no_redirect_rows_collected")
        return blockers
    for row in rows:
        if not row["old_dj_id"] or not row["canonical_dj_id"]:
            blockers.append("blank_redirect_id")
        if row["old_dj_id"] == row["canonical_dj_id"]:
            blockers.append("old_equals_canonical")
        if not conn.execute("SELECT 1 FROM dj_profile WHERE dj_id=?", (row["canonical_dj_id"],)).fetchone():
            blockers.append(f"canonical_profile_missing:{row['canonical_dj_id']}")
    refs = old_reference_counts(conn, [row["old_dj_id"] for row in rows])
    for table, count in refs.items():
        if count:
            blockers.append(f"old_id_references_still_present:{table}:{count}")
    return sorted(set(blockers))


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS dj_identity_redirect (
          old_dj_id TEXT PRIMARY KEY,
          canonical_dj_id TEXT NOT NULL,
          group_id TEXT,
          source_story_id TEXT NOT NULL,
          source_report_path TEXT NOT NULL,
          source_report_sha256 TEXT NOT NULL,
          created_at TEXT NOT NULL,
          redirect_kind TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_dj_identity_redirect_canonical
          ON dj_identity_redirect(canonical_dj_id);
        """
    )


def readback(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> dict[str, Any]:
    old_ids = [row["old_dj_id"] for row in rows]
    if old_ids:
        ph = ",".join("?" for _ in old_ids)
        materialized = int(conn.execute(f"SELECT COUNT(*) FROM dj_identity_redirect WHERE old_dj_id IN ({ph})", old_ids).fetchone()[0])
    else:
        materialized = 0
    invalid_canonical = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM dj_identity_redirect r
            LEFT JOIN dj_profile p ON p.dj_id = r.canonical_dj_id
            WHERE p.dj_id IS NULL
            """
        ).fetchone()[0]
    )
    total = int(conn.execute("SELECT COUNT(*) FROM dj_identity_redirect").fetchone()[0])
    refs = old_reference_counts(conn, old_ids)
    return {
        "ok": materialized == len(rows) and invalid_canonical == 0 and all(count == 0 for count in refs.values()),
        "expected_rows": len(rows),
        "materialized_rows": materialized,
        "total_redirect_rows": total,
        "invalid_canonical_count": invalid_canonical,
        "old_reference_counts": refs,
        "source_story_counts": dict(
            Counter(
                row[0]
                for row in conn.execute(
                    "SELECT source_story_id FROM dj_identity_redirect ORDER BY source_story_id"
                ).fetchall()
            )
        ),
    }


def run_write(
    *,
    db3_path: Path,
    out_dir: Path,
    source_reports: list[Path],
    execute: bool,
    busy_timeout_ms: int,
    max_lock_attempts: int,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    collected, source_report_status = collect_redirect_rows(source_reports)
    rows, conflicts = dedupe_redirect_rows(collected)
    lock_path = out_dir / "atlas_identity_redirect_db3_write_s157.lock"
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "current_story_id": CURRENT_STORY_ID,
        "generated_at": now_iso(),
        "decision": "",
        "execute_requested": execute,
        "source_reports": source_report_status,
        "collected_redirect_count": len(collected),
        "deduped_redirect_count": len(rows),
        "conflict_count": len(conflicts),
        "conflict_sample": conflicts[:5],
        "lock_path": rel_path(lock_path),
        "backup_path": "",
        "backup_sha256": "",
        "blocked_reasons": [],
        "prewrite_readback": {},
        "postwrite_readback": {},
        "write_state": {
            "write_executed": False,
            "committed": False,
            "rollback_performed": False,
            "database_mutations": False,
            "db3_identity_redirect_write": False,
        },
        "safety": {
            "db1_mutation": False,
            "db2_projection": False,
            "relation_table_redirect": False,
            "profile_reinsert": False,
            "release_rebuild": False,
            "deploy_upload_review": False,
            "provider_or_llm_call": False,
            "secret_read": False,
            "service_restart": False,
            "broad_disk_scan": False,
        },
    }
    conn = s148.connect_rw(db3_path, busy_timeout_ms=busy_timeout_ms)
    try:
        blockers = validate_rows(conn, rows, conflicts)
    finally:
        conn.close()
    if blockers:
        result["blocked_reasons"] = blockers
        result["decision"] = "atlas_identity_redirect_db3_write_s157_blocked_prewrite"
        return result
    if not execute:
        result["decision"] = "atlas_identity_redirect_db3_write_s157_dry_run_ready"
        return result

    with s148.FileLock(lock_path, max_attempts=max_lock_attempts):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = out_dir / f"backup_before_identity_redirect_db3_write_s157_{stamp}.sqlite"
        shutil.copy2(db3_path, backup_path)
        result["backup_path"] = rel_path(backup_path)
        result["backup_sha256"] = s148.sha256_file(backup_path)
        conn = s148.connect_rw(db3_path, busy_timeout_ms=busy_timeout_ms)
        try:
            conn.execute("BEGIN IMMEDIATE")
            ensure_schema(conn)
            stamp_iso = now_iso()
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO dj_identity_redirect (
                      old_dj_id,
                      canonical_dj_id,
                      group_id,
                      source_story_id,
                      source_report_path,
                      source_report_sha256,
                      created_at,
                      redirect_kind
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(old_dj_id) DO UPDATE SET
                      canonical_dj_id=excluded.canonical_dj_id,
                      group_id=excluded.group_id,
                      source_story_id=excluded.source_story_id,
                      source_report_path=excluded.source_report_path,
                      source_report_sha256=excluded.source_report_sha256,
                      created_at=excluded.created_at,
                      redirect_kind=excluded.redirect_kind
                    """,
                    (
                        row["old_dj_id"],
                        row["canonical_dj_id"],
                        row["group_id"],
                        row["source_story_id"],
                        row["source_report_path"],
                        row["source_report_sha256"],
                        stamp_iso,
                        row["redirect_kind"],
                    ),
                )
            precommit = readback(conn, rows)
            result["prewrite_readback"] = precommit
            if not precommit["ok"]:
                conn.rollback()
                result["write_state"]["rollback_performed"] = True
                result["blocked_reasons"].append("precommit_readback_failed")
                result["decision"] = "atlas_identity_redirect_db3_write_s157_blocked_precommit_readback"
                return result
            conn.commit()
            postcommit = readback(conn, rows)
            result["postwrite_readback"] = postcommit
            if not postcommit["ok"]:
                result["blocked_reasons"].append("postcommit_readback_failed_manual_restore_required")
                result["decision"] = "atlas_identity_redirect_db3_write_s157_blocked_postcommit_readback"
                return result
            result["write_state"] = {
                "write_executed": True,
                "committed": True,
                "rollback_performed": False,
                "database_mutations": True,
                "db3_identity_redirect_write": True,
            }
            result["decision"] = "atlas_identity_redirect_db3_write_s157_committed_with_readback"
            return result
        except Exception as exc:  # noqa: BLE001
            try:
                conn.rollback()
                result["write_state"]["rollback_performed"] = True
            except sqlite3.Error:
                pass
            result["blocked_reasons"].append(f"{exc.__class__.__name__}:{exc}")
            result["decision"] = "atlas_identity_redirect_db3_write_s157_blocked_exception"
            return result
        finally:
            conn.close()


def render_markdown(report: dict[str, Any], paths: dict[str, str]) -> str:
    post = report.get("postwrite_readback") or report.get("prewrite_readback") or {}
    lines = [
        "# Atlas Identity Redirect DB3 Write S157",
        "",
        f"- Decision: `{report.get('decision')}`",
        f"- Execute requested: `{report.get('execute_requested')}`",
        f"- Collected redirects: `{report.get('collected_redirect_count')}`",
        f"- Deduped redirects: `{report.get('deduped_redirect_count')}`",
        f"- Conflicts: `{report.get('conflict_count')}`",
        f"- Committed: `{(report.get('write_state') or {}).get('committed')}`",
        f"- Total DB3 redirect rows: `{post.get('total_redirect_rows')}`",
        f"- Invalid canonical redirects: `{post.get('invalid_canonical_count')}`",
        f"- Old-reference counts: `{post.get('old_reference_counts')}`",
        f"- Backup: `{report.get('backup_path')}`",
        "",
        "## Evidence",
        "",
        f"- JSON: `{paths['json']}`",
        f"- Markdown: `{paths['markdown']}`",
        "",
        "## Boundary",
        "",
        "- This writes only the DB3 `dj_identity_redirect` mapping table.",
        "- It does not reinsert old profiles, rewrite DB2, rebuild release packages, deploy, upload, review, read secrets, or call providers/models.",
        "- Full relation-identity clearance still requires the remaining empty-normalized and same-normalized DB3 review lanes.",
        "",
    ]
    if report.get("blocked_reasons"):
        lines.extend(["## Blockers", ""])
        for reason in report["blocked_reasons"]:
            lines.append(f"- `{reason}`")
        lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--source-report", action="append", type=Path, default=[])
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--busy-timeout-ms", type=int, default=5000)
    parser.add_argument("--max-lock-attempts", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source_reports = args.source_report or DEFAULT_SOURCE_REPORTS
    report = run_write(
        db3_path=args.db3,
        out_dir=args.out_dir,
        source_reports=source_reports,
        execute=args.execute,
        busy_timeout_ms=args.busy_timeout_ms,
        max_lock_attempts=args.max_lock_attempts,
    )
    json_path = args.out_dir / "atlas_identity_redirect_db3_write_s157.json"
    md_path = args.out_dir / "atlas_identity_redirect_db3_write_s157.md"
    paths = {"json": rel_path(json_path), "markdown": rel_path(md_path), "scorecard": rel_path(args.scorecard)}
    atomic_write_json(json_path, report)
    atomic_write_text(md_path, render_markdown(report, paths))
    atomic_write_text(args.scorecard, render_markdown(report, paths))
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "committed": (report.get("write_state") or {}).get("committed"),
                "deduped_redirect_count": report.get("deduped_redirect_count"),
                "json": paths["json"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["decision"] in {"atlas_identity_redirect_db3_write_s157_committed_with_readback", "atlas_identity_redirect_db3_write_s157_dry_run_ready"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
