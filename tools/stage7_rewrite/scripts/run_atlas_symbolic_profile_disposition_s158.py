#!/usr/bin/env python3
"""Write DB3 dispositions for source-backed symbolic DJ stage names."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.scripts import run_atlas_relation_identity_db3_canary_s148 as s148


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S158"
SCHEMA_VERSION = "atlas_symbolic_profile_disposition_s158.v1"

DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_symbolic_profile_disposition_s158_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_SYMBOLIC_PROFILE_DISPOSITION_S158_20260602.md"


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


def normalized_token(value: Any) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").strip().lower())


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS dj_identity_profile_disposition (
          dj_id TEXT PRIMARY KEY,
          disposition TEXT NOT NULL,
          reason_code TEXT NOT NULL,
          source_story_id TEXT NOT NULL,
          source_ref_count INTEGER NOT NULL,
          event_count INTEGER NOT NULL,
          subject_present INTEGER NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_dj_identity_profile_disposition_disposition
          ON dj_identity_profile_disposition(disposition);
        """
    )


def collect_symbolic_profiles(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in conn.execute(
        """
        SELECT dj_id, display_name, normalized_name, city_primary, event_count, venue_count, collaborator_count
        FROM dj_profile
        WHERE COALESCE(dj_id, '') <> ''
        ORDER BY dj_id
        """
    ).fetchall():
        dj_id = str(row[0])
        display_name = str(row[1] or "")
        normalized_name = str(row[2] or "")
        if normalized_token(normalized_name):
            continue
        event_count, source_ref_count = conn.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT source_ref_id)
            FROM dj_event
            WHERE dj_id=?
              AND COALESCE(source_ref_id, '') <> ''
            """,
            (dj_id,),
        ).fetchone()
        subject_present = int(bool(conn.execute("SELECT 1 FROM subject WHERE subject_id=?", (dj_id,)).fetchone()))
        rows.append(
            {
                "dj_id": dj_id,
                "display_name": display_name,
                "normalized_name": normalized_name,
                "city_primary": str(row[3] or ""),
                "profile_event_count": int(row[4] or 0),
                "profile_venue_count": int(row[5] or 0),
                "profile_collaborator_count": int(row[6] or 0),
                "event_count": int(event_count or 0),
                "source_ref_count": int(source_ref_count or 0),
                "subject_present": subject_present,
                "eligible": bool(display_name.strip() and normalized_name.strip() and event_count and source_ref_count and subject_present),
            }
        )
    return rows


def validate_rows(rows: list[dict[str, Any]]) -> list[str]:
    blockers: list[str] = []
    if not rows:
        blockers.append("no_symbolic_profiles_found")
    not_eligible = [row for row in rows if not row["eligible"]]
    if not_eligible:
        blockers.append(f"symbolic_profiles_without_subject_event_or_source_ref:{len(not_eligible)}")
    return blockers


def readback(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [row["dj_id"] for row in rows]
    if not ids:
        return {"ok": False, "expected_rows": 0, "materialized_rows": 0}
    ph = ",".join("?" for _ in ids)
    materialized = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM dj_identity_profile_disposition
            WHERE dj_id IN ({ph})
              AND disposition='symbolic_stage_name_preserve'
              AND source_story_id=?
              AND source_ref_count > 0
              AND event_count > 0
              AND subject_present = 1
            """,
            [*ids, CURRENT_STORY_ID],
        ).fetchone()[0]
    )
    total = int(conn.execute("SELECT COUNT(*) FROM dj_identity_profile_disposition").fetchone()[0])
    return {
        "ok": materialized == len(rows),
        "expected_rows": len(rows),
        "materialized_rows": materialized,
        "total_disposition_rows": total,
    }


def run_write(
    *,
    db3_path: Path,
    out_dir: Path,
    execute: bool,
    busy_timeout_ms: int,
    max_lock_attempts: int,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    lock_path = out_dir / "atlas_symbolic_profile_disposition_s158.lock"
    conn = s148.connect_rw(db3_path, busy_timeout_ms=busy_timeout_ms)
    try:
        rows = collect_symbolic_profiles(conn)
    finally:
        conn.close()
    blockers = validate_rows(rows)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "current_story_id": CURRENT_STORY_ID,
        "generated_at": now_iso(),
        "decision": "",
        "execute_requested": execute,
        "symbolic_profile_count": len(rows),
        "eligible_count": sum(1 for row in rows if row["eligible"]),
        "blocked_count": sum(1 for row in rows if not row["eligible"]),
        "blocked_sample": [row for row in rows if not row["eligible"]][:20],
        "symbolic_profile_sample": rows[:40],
        "lock_path": rel_path(lock_path),
        "backup_path": "",
        "backup_sha256": "",
        "blocked_reasons": blockers,
        "prewrite_readback": {},
        "postwrite_readback": {},
        "write_state": {
            "write_executed": False,
            "committed": False,
            "rollback_performed": False,
            "database_mutations": False,
            "db3_profile_disposition_write": False,
        },
        "safety": {
            "profile_field_mutation": False,
            "relation_table_redirect": False,
            "db1_mutation": False,
            "db2_projection": False,
            "release_rebuild": False,
            "deploy_upload_review": False,
            "provider_or_llm_call": False,
            "secret_read": False,
            "service_restart": False,
            "broad_disk_scan": False,
        },
    }
    if blockers:
        report["decision"] = "atlas_symbolic_profile_disposition_s158_blocked_prewrite"
        return report
    if not execute:
        report["decision"] = "atlas_symbolic_profile_disposition_s158_dry_run_ready"
        return report

    with s148.FileLock(lock_path, max_attempts=max_lock_attempts):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = out_dir / f"backup_before_symbolic_profile_disposition_s158_{stamp}.sqlite"
        shutil.copy2(db3_path, backup_path)
        report["backup_path"] = rel_path(backup_path)
        report["backup_sha256"] = s148.sha256_file(backup_path)
        conn = s148.connect_rw(db3_path, busy_timeout_ms=busy_timeout_ms)
        try:
            conn.execute("BEGIN IMMEDIATE")
            ensure_schema(conn)
            stamp_iso = now_iso()
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO dj_identity_profile_disposition (
                      dj_id,
                      disposition,
                      reason_code,
                      source_story_id,
                      source_ref_count,
                      event_count,
                      subject_present,
                      created_at
                    )
                    VALUES (?, 'symbolic_stage_name_preserve', 'source_backed_symbolic_stage_name', ?, ?, ?, ?, ?)
                    ON CONFLICT(dj_id) DO UPDATE SET
                      disposition=excluded.disposition,
                      reason_code=excluded.reason_code,
                      source_story_id=excluded.source_story_id,
                      source_ref_count=excluded.source_ref_count,
                      event_count=excluded.event_count,
                      subject_present=excluded.subject_present,
                      created_at=excluded.created_at
                    """,
                    (
                        row["dj_id"],
                        CURRENT_STORY_ID,
                        row["source_ref_count"],
                        row["event_count"],
                        row["subject_present"],
                        stamp_iso,
                    ),
                )
            precommit = readback(conn, rows)
            report["prewrite_readback"] = precommit
            if not precommit["ok"]:
                conn.rollback()
                report["write_state"]["rollback_performed"] = True
                report["blocked_reasons"].append("precommit_readback_failed")
                report["decision"] = "atlas_symbolic_profile_disposition_s158_blocked_precommit_readback"
                return report
            conn.commit()
            postcommit = readback(conn, rows)
            report["postwrite_readback"] = postcommit
            if not postcommit["ok"]:
                report["blocked_reasons"].append("postcommit_readback_failed_manual_restore_required")
                report["decision"] = "atlas_symbolic_profile_disposition_s158_blocked_postcommit_readback"
                return report
            report["write_state"] = {
                "write_executed": True,
                "committed": True,
                "rollback_performed": False,
                "database_mutations": True,
                "db3_profile_disposition_write": True,
            }
            report["decision"] = "atlas_symbolic_profile_disposition_s158_committed_with_readback"
            return report
        except Exception as exc:  # noqa: BLE001
            try:
                conn.rollback()
                report["write_state"]["rollback_performed"] = True
            except sqlite3.Error:
                pass
            report["blocked_reasons"].append(f"{exc.__class__.__name__}:{exc}")
            report["decision"] = "atlas_symbolic_profile_disposition_s158_blocked_exception"
            return report
        finally:
            conn.close()


def render_markdown(report: dict[str, Any], paths: dict[str, str]) -> str:
    post = report.get("postwrite_readback") or report.get("prewrite_readback") or {}
    lines = [
        "# Atlas Symbolic Profile Disposition S158",
        "",
        f"- Decision: `{report.get('decision')}`",
        f"- Execute requested: `{report.get('execute_requested')}`",
        f"- Symbolic profile count: `{report.get('symbolic_profile_count')}`",
        f"- Eligible count: `{report.get('eligible_count')}`",
        f"- Blocked count: `{report.get('blocked_count')}`",
        f"- Committed: `{(report.get('write_state') or {}).get('committed')}`",
        f"- Materialized rows: `{post.get('materialized_rows')}`",
        f"- Backup: `{report.get('backup_path')}`",
        "",
        "## Evidence",
        "",
        f"- JSON: `{paths['json']}`",
        f"- Markdown: `{paths['markdown']}`",
        "",
        "## Boundary",
        "",
        "- This writes only a DB3 disposition table for source-backed symbolic stage names.",
        "- It does not change profile names, relation tables, DB2, release packages, deploy, upload, review, secrets, or provider/model state.",
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
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--busy-timeout-ms", type=int, default=5000)
    parser.add_argument("--max-lock-attempts", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_write(
        db3_path=args.db3,
        out_dir=args.out_dir,
        execute=args.execute,
        busy_timeout_ms=args.busy_timeout_ms,
        max_lock_attempts=args.max_lock_attempts,
    )
    json_path = args.out_dir / "atlas_symbolic_profile_disposition_s158.json"
    md_path = args.out_dir / "atlas_symbolic_profile_disposition_s158.md"
    paths = {"json": rel_path(json_path), "markdown": rel_path(md_path), "scorecard": rel_path(args.scorecard)}
    atomic_write_json(json_path, report)
    atomic_write_text(md_path, render_markdown(report, paths))
    atomic_write_text(args.scorecard, render_markdown(report, paths))
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "committed": (report.get("write_state") or {}).get("committed"),
                "symbolic_profile_count": report.get("symbolic_profile_count"),
                "json": paths["json"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["decision"] in {"atlas_symbolic_profile_disposition_s158_committed_with_readback", "atlas_symbolic_profile_disposition_s158_dry_run_ready"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
