#!/usr/bin/env python3
"""Write DB3 non-person dispositions for source-backed lineup/collective artifacts.

S181 handles the safe subset of the risk lane that should not be identity-merged:
lineup/count labels, collectives/labels/bands, guest/resident labels, and role or
bio-sentence artifacts. Collaboration markers remain blocked.
"""
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

from tools.stage7_rewrite.scripts import build_atlas_relation_identity_complex_classifier_s164 as s164
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_db3_canary_s148 as s148
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_safe_variant_batch_s159 as s159
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_multivenue_batch_s169 as s169
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_singlevenue_batch_s171 as s171
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_source_anchor_batch_s167 as s167


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S181"
SCHEMA_VERSION = "atlas_relation_identity_non_person_disposition_s181.v1"

DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_non_person_disposition_s181_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_NON_PERSON_DISPOSITION_S181_20260602.md"

SAFE_NON_PERSON_RISK_REASONS = {
    "lineup_or_count_marker",
    "collective_label_or_band_marker",
    "guest_or_resident_marker",
    "bio_sentence_or_role_marker",
}
DISPOSITION = "non_person_lineup_collective_or_role_artifact"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def rel_path(path: Path) -> str:
    return s167.rel_path(path)


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


def profile_rows(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    return [candidate["canonical_profile"], *list(candidate.get("merge_profiles") or [])]


def collect_candidates(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    blocker_counts: Counter[str] = Counter()
    for (city, token), group in sorted(s164.grouped_profile_rows(conn).items()):
        ids = sorted({str(row["dj_id"]) for row in group})
        if len(ids) <= 1:
            continue
        classified = s164.classify_row(group, city=city, token=token, conn=conn)
        values = [*classified["display_names"], *classified["normalized_names"], classified["identity_token"]]
        risk_reasons = set(s171.s171_risk_reasons(values))
        if not risk_reasons:
            continue
        for reason in sorted(risk_reasons):
            reason_counts[reason] += 1
        blockers: list[str] = []
        if not risk_reasons <= SAFE_NON_PERSON_RISK_REASONS:
            blockers.append("risk_reason_not_safe_non_person_disposition")
        candidate = s159.build_candidate(city, token, group)
        if not s169.profile_evidence_ok(candidate):
            blockers.append("profile_source_ref_or_subject_evidence_missing")
        if blockers:
            for blocker in blockers:
                blocker_counts[blocker] += 1
            rejected.append(
                {
                    **classified,
                    "s181_risk_reasons": sorted(risk_reasons),
                    "s181_blockers": blockers,
                }
            )
            continue
        disposition_rows = []
        for row in profile_rows(candidate):
            disposition_rows.append(
                {
                    "dj_id": row["dj_id"],
                    "display_name": row["display_name"],
                    "normalized_name": row["normalized_name"],
                    "source_ref_count": int(row.get("source_ref_count") or 0),
                    "event_count": int(row.get("event_rows_with_source_ref") or row.get("event_count") or 0),
                    "subject_present": int(row.get("subject_present") or 0),
                }
            )
        candidates.append(
            {
                "prewrite_row_id": f"s181:{s159.group_hash(city, token, ids)}",
                "group_id": classified["group_id"],
                "identity_token": classified["identity_token"],
                "dj_ids": classified["dj_ids"],
                "display_names": classified["display_names"],
                "normalized_names": classified["normalized_names"],
                "row_count": classified["row_count"],
                "s181_risk_reasons": sorted(risk_reasons),
                "disposition": DISPOSITION,
                "reason_code": "+".join(sorted(risk_reasons)),
                "profile_disposition_rows": disposition_rows,
                "source_ref_backed": True,
                "safety_basis": [
                    "risk_reasons_subset_of_safe_non_person_markers",
                    "collaboration_marker_absent",
                    "subject_present_for_all_ids",
                    "source_ref_backed_event_for_all_ids",
                    "writes_disposition_table_only",
                    "audit_excludes_only_when_whole_same_normalized_group_is_dispositioned",
                ],
            }
        )
    unique_profile_ids = sorted({row["dj_id"] for item in candidates for row in item["profile_disposition_rows"]})
    state = {
        "candidate_group_count": len(candidates),
        "candidate_profile_count": len(unique_profile_ids),
        "rejected_group_count": len(rejected),
        "risk_reason_counts": dict(sorted(reason_counts.items())),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "table_counts": s148.table_counts(conn),
    }
    return candidates, rejected, state


def readback(conn: sqlite3.Connection, profile_ids: list[str]) -> dict[str, Any]:
    if not profile_ids:
        return {"ok": False, "expected_rows": 0, "materialized_rows": 0}
    ph = ",".join("?" for _ in profile_ids)
    materialized = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM dj_identity_profile_disposition
            WHERE dj_id IN ({ph})
              AND disposition=?
              AND source_story_id=?
              AND source_ref_count > 0
              AND event_count > 0
              AND subject_present = 1
            """,
            [*profile_ids, DISPOSITION, CURRENT_STORY_ID],
        ).fetchone()[0]
    )
    total = int(conn.execute("SELECT COUNT(*) FROM dj_identity_profile_disposition").fetchone()[0])
    return {
        "ok": materialized == len(profile_ids),
        "expected_rows": len(profile_ids),
        "materialized_rows": materialized,
        "total_disposition_rows": total,
    }


def write_queues(out_dir: Path, candidates: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> dict[str, str]:
    artifacts = {
        "candidates_jsonl": rel_path(out_dir / "non_person_disposition_candidates_s181.jsonl"),
        "rejected_jsonl": rel_path(out_dir / "non_person_disposition_rejected_s181.jsonl"),
    }
    write_jsonl(out_dir / "non_person_disposition_candidates_s181.jsonl", candidates)
    write_jsonl(out_dir / "non_person_disposition_rejected_s181.jsonl", rejected)
    return artifacts


def run_write(
    *,
    db3_path: Path,
    out_dir: Path,
    execute: bool,
    busy_timeout_ms: int,
    max_lock_attempts: int,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = s159.connect_ro(db3_path)
    try:
        candidates, rejected, initial_state = collect_candidates(conn)
    finally:
        conn.close()
    artifacts = write_queues(out_dir, candidates, rejected)
    profile_rows_to_write = {
        row["dj_id"]: {**row, "reason_code": item["reason_code"]}
        for item in candidates
        for row in item["profile_disposition_rows"]
    }
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "current_story_id": CURRENT_STORY_ID,
        "generated_at": now_iso(),
        "decision": "",
        "execute_requested": execute,
        "source_inputs": {"db3": rel_path(db3_path)},
        "artifacts": artifacts,
        "initial_state": {**initial_state, "candidate_sample": candidates[:30], "rejected_sample": rejected[:30]},
        "candidate_group_count": len(candidates),
        "candidate_profile_count": len(profile_rows_to_write),
        "backup_path": "",
        "backup_sha256": "",
        "lock_path": rel_path(out_dir / "atlas_relation_identity_non_person_disposition_s181.lock"),
        "precommit_readback": {},
        "postcommit_readback": {},
        "blocked_reasons": [],
        "write_state": {
            "write_executed": False,
            "committed": False,
            "rollback_performed": False,
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
    if not candidates:
        report["decision"] = "atlas_relation_identity_non_person_disposition_s181_blocked_no_candidates"
        return report
    if not execute:
        report["decision"] = "atlas_relation_identity_non_person_disposition_s181_dry_run_ready"
        return report

    lock_path = out_dir / "atlas_relation_identity_non_person_disposition_s181.lock"
    with s148.FileLock(lock_path, max_attempts=max_lock_attempts):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = out_dir / f"backup_before_relation_identity_non_person_disposition_s181_{stamp}.sqlite"
        shutil.copy2(db3_path, backup_path)
        report["backup_path"] = rel_path(backup_path)
        report["backup_sha256"] = s148.sha256_file(backup_path)
        conn = s148.connect_rw(db3_path, busy_timeout_ms=busy_timeout_ms)
        try:
            conn.execute("BEGIN IMMEDIATE")
            ensure_schema(conn)
            stamp_iso = now_iso()
            for row in profile_rows_to_write.values():
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
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                        DISPOSITION,
                        row["reason_code"],
                        CURRENT_STORY_ID,
                        row["source_ref_count"],
                        row["event_count"],
                        row["subject_present"],
                        stamp_iso,
                    ),
                )
            precommit = readback(conn, sorted(profile_rows_to_write))
            report["precommit_readback"] = precommit
            if not precommit["ok"]:
                conn.rollback()
                report["write_state"]["rollback_performed"] = True
                report["blocked_reasons"].append("precommit_readback_failed")
                report["decision"] = "atlas_relation_identity_non_person_disposition_s181_blocked_precommit_readback"
                return report
            conn.commit()
            postcommit = readback(conn, sorted(profile_rows_to_write))
            report["postcommit_readback"] = postcommit
            if not postcommit["ok"]:
                report["blocked_reasons"].append("postcommit_readback_failed_manual_restore_required")
                report["decision"] = "atlas_relation_identity_non_person_disposition_s181_blocked_postcommit_readback"
                return report
            report["write_state"] = {
                "write_executed": True,
                "committed": True,
                "rollback_performed": False,
                "db3_profile_disposition_write": True,
            }
            report["decision"] = "atlas_relation_identity_non_person_disposition_s181_committed_with_readback"
            return report
        except Exception as exc:  # noqa: BLE001
            try:
                conn.rollback()
                report["write_state"]["rollback_performed"] = True
            except sqlite3.Error:
                pass
            report["blocked_reasons"].append(f"{exc.__class__.__name__}:{exc}")
            report["decision"] = "atlas_relation_identity_non_person_disposition_s181_blocked_exception"
            return report
        finally:
            conn.close()


def render_markdown(report: dict[str, Any]) -> str:
    readback_payload = report.get("postcommit_readback") or report.get("precommit_readback") or {}
    lines = [
        "# Weekly Atlas Relation Identity Non-Person Disposition S181",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Execute requested: `{str(report['execute_requested']).lower()}`",
        f"- Candidate groups: `{report['candidate_group_count']}`",
        f"- Candidate profiles: `{report['candidate_profile_count']}`",
        f"- Committed: `{str((report.get('write_state') or {}).get('committed')).lower()}`",
        f"- Materialized rows: `{readback_payload.get('materialized_rows')}`",
        f"- Backup: `{report.get('backup_path', '')}`",
        "",
        "## Scope",
        "",
        "- Writes only DB3 `dj_identity_profile_disposition` rows.",
        "- Safe risk reasons are lineup/count, collective/label/band, guest/resident, and role/bio-sentence markers.",
        "- Collaboration markers remain blocked.",
        "- Audit exclusion applies only when a whole same-normalized group is source-backed and dispositioned.",
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
    json_path = args.out_dir / "atlas_relation_identity_non_person_disposition_s181.json"
    md_path = args.out_dir / "atlas_relation_identity_non_person_disposition_s181.md"
    atomic_write_json(json_path, report)
    atomic_write_text(md_path, render_markdown(report))
    atomic_write_text(args.scorecard, render_markdown(report))
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "committed": (report.get("write_state") or {}).get("committed"),
                "candidate_groups": report["candidate_group_count"],
                "candidate_profiles": report["candidate_profile_count"],
                "materialized_rows": (report.get("postcommit_readback") or {}).get("materialized_rows"),
                "json": str(json_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["decision"] in {
        "atlas_relation_identity_non_person_disposition_s181_committed_with_readback",
        "atlas_relation_identity_non_person_disposition_s181_dry_run_ready",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
