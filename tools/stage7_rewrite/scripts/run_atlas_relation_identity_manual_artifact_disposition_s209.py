#!/usr/bin/env python3
"""Write strict manual-lane non-person artifact dispositions.

S209 handles only the narrow manual-review subset that is clearly not a DJ
person identity: band/collective artifacts and count/role lineup fragments. It
does not merge identities and does not update profile, subject, event, venue, or
collaborator tables. Ambiguous aka/slash/stage-name variants remain blocked for
source-provider evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import re
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
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_non_person_disposition_s181 as s181
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_safe_variant_batch_s159 as s159
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_multivenue_batch_s169 as s169
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_source_anchor_batch_s167 as s167
from tools.stage7_rewrite.scripts import build_atlas_relation_identity_complex_classifier_s164 as s164


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S209"
REPORT_STEM = "atlas_relation_identity_manual_artifact_disposition_s209"
SCHEMA_VERSION = f"{REPORT_STEM}.v1"
DISPOSITION = "non_person_lineup_collective_or_role_artifact"

DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_INPUT = (
    REPORTS_ROOT
    / "atlas_relation_identity_source_provider_acquisition_s204_after_s202_full_20260602"
    / "manual_review_rows_s185.jsonl"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_manual_artifact_disposition_s209_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_MANUAL_ARTIFACT_DISPOSITION_S209_20260602.md"

AKA_RE = re.compile(r"(\ba\.?\s*k\.?\s*a\.?\b|\baka\b|又名|别名)", re.I)
BAND_RE = re.compile(r"(乐队|\bband\b|collective|crew)", re.I)
LINEUP_COUNT_ROLE_RE = re.compile(r"(\d+\s*位\s*(?:dj|音乐人)|\d+\s*(?:djs|dj)\b)", re.I)
AMBIGUOUS_ALIAS_RE = re.compile(r"[/+]|(?:\s+x\s+)|\bwith\b", re.I)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel_path(path: Path) -> str:
    return s167.rel_path(path)


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


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def display_names(row: dict[str, Any]) -> list[str]:
    values = row.get("display_names") or (row.get("source_group_row") or {}).get("display_names") or []
    return [str(value or "").strip() for value in values if str(value or "").strip()]


def safe_manual_disposition_reason(displays: list[str], risk_reasons: list[str], s159_reasons: list[str]) -> tuple[str, list[str]]:
    text = " ".join(displays)
    blockers: list[str] = []
    if not displays:
        blockers.append("display_names_missing")
    if AKA_RE.search(text):
        blockers.append("aka_marker_not_non_person_disposition")
    if AMBIGUOUS_ALIAS_RE.search(text) and not BAND_RE.search(text) and not LINEUP_COUNT_ROLE_RE.search(text):
        blockers.append("ambiguous_alias_separator_without_non_person_marker")
    risk_set = set(risk_reasons)
    if BAND_RE.search(text) and all(BAND_RE.search(display) for display in displays):
        return "band_collective_brand", blockers
    if LINEUP_COUNT_ROLE_RE.search(text) and (
        "lineup_or_count_marker" in risk_set or "bio_sentence_or_role_marker" in risk_set or "risk_word_present" in s159_reasons
    ):
        return "lineup_role_event_fragment", blockers
    blockers.append("no_strict_non_person_manual_marker")
    return "", blockers


def profile_rows(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    return [candidate["canonical_profile"], *list(candidate.get("merge_profiles") or [])]


def disposition_rows_for_candidate(candidate: dict[str, Any], reason_code: str) -> list[dict[str, Any]]:
    return [
        {
            "dj_id": row["dj_id"],
            "display_name": row["display_name"],
            "normalized_name": row["normalized_name"],
            "source_ref_count": int(row.get("source_ref_count") or 0),
            "event_count": int(row.get("event_rows_with_source_ref") or row.get("event_count") or 0),
            "subject_present": int(row.get("subject_present") or 0),
            "reason_code": reason_code,
        }
        for row in profile_rows(candidate)
    ]


def live_lookup(conn: sqlite3.Connection) -> dict[frozenset[str], tuple[str, str, list[dict[str, Any]]]]:
    result: dict[frozenset[str], tuple[str, str, list[dict[str, Any]]]] = {}
    for (city, token), group in s164.grouped_profile_rows(conn).items():
        ids = frozenset(str(row["dj_id"]) for row in group)
        if len(ids) > 1:
            result[ids] = (city, token, group)
    return result


def collect_candidates(conn: sqlite3.Connection, input_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    rows = read_jsonl(input_path)
    lookup = live_lookup(conn)
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    blocker_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    for row in rows:
        dj_ids = [str(value) for value in row.get("dj_ids") or [] if str(value)]
        group_key = frozenset(dj_ids)
        live = lookup.get(group_key)
        source_group = row.get("source_group_row") or {}
        displays = display_names(row)
        risk_reasons = list(source_group.get("s183_risk_reasons") or row.get("s183_risk_reasons") or [])
        s159_reasons = list(source_group.get("s159_rejection_reasons") or [])
        reason_code, blockers = safe_manual_disposition_reason(displays, risk_reasons, s159_reasons)
        if not live:
            blockers.append("live_group_not_found_or_already_changed")
        if not reason_code:
            blockers.append("strict_manual_disposition_reason_missing")
        if blockers:
            for blocker in sorted(set(blockers)):
                blocker_counts[blocker] += 1
            rejected.append(
                {
                    "group_id": source_group.get("group_id") or row.get("group_id"),
                    "dj_ids": dj_ids,
                    "display_names": displays,
                    "s209_blockers": sorted(set(blockers)),
                    "s183_risk_reasons": risk_reasons,
                    "s159_rejection_reasons": s159_reasons,
                }
            )
            continue
        city, token, group = live
        classified = s164.classify_row(group, city=city, token=token, conn=conn)
        candidate = s159.build_candidate(city, token, group)
        if not s169.profile_evidence_ok(candidate):
            rejected.append(
                {
                    **classified,
                    "display_names": displays,
                    "s209_blockers": ["profile_source_ref_or_subject_evidence_missing"],
                    "s183_risk_reasons": risk_reasons,
                    "s159_rejection_reasons": s159_reasons,
                }
            )
            blocker_counts["profile_source_ref_or_subject_evidence_missing"] += 1
            continue
        reason_counts[reason_code] += 1
        candidate["prewrite_row_id"] = f"s209:{s159.group_hash(city, token, sorted(dj_ids))}"
        candidate["current_story_id"] = CURRENT_STORY_ID
        candidate["s209_input_group_id"] = source_group.get("group_id") or row.get("group_id")
        candidate["disposition"] = DISPOSITION
        candidate["reason_code"] = reason_code
        candidate["profile_disposition_rows"] = disposition_rows_for_candidate(candidate, reason_code)
        candidate["safety_basis"] = [
            "manual_review_lane_only",
            "strict_non_person_marker_present",
            "aka_and_ambiguous_alias_markers_excluded",
            "subject_present_for_all_ids",
            "source_ref_backed_event_for_all_ids",
            "writes_disposition_table_only",
            "does_not_merge_identity",
        ]
        candidates.append(candidate)
    state = {
        "input_manual_rows": len(rows),
        "candidate_group_count": len(candidates),
        "candidate_profile_count": len({item["dj_id"] for row in candidates for item in row["profile_disposition_rows"]}),
        "rejected_group_count": len(rejected),
        "reason_counts": dict(sorted(reason_counts.items())),
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
    return {"ok": materialized == len(profile_ids), "expected_rows": len(profile_ids), "materialized_rows": materialized}


def run_write(
    *,
    db3_path: Path,
    input_path: Path,
    out_dir: Path,
    scorecard_path: Path,
    execute: bool,
    busy_timeout_ms: int,
    max_lock_attempts: int,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = s159.connect_ro(db3_path)
    try:
        candidates, rejected, initial_state = collect_candidates(conn, input_path)
    finally:
        conn.close()
    write_jsonl(out_dir / "s209_manual_artifact_disposition_candidates.jsonl", candidates)
    write_jsonl(out_dir / "s209_manual_artifact_disposition_rejected.jsonl", rejected)
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
        "input_path": rel_path(input_path),
        "candidate_group_count": len(candidates),
        "candidate_profile_count": len(profile_rows_to_write),
        "initial_state": {**initial_state, "candidate_sample": candidates[:20], "rejected_sample": rejected[:20]},
        "backup_path": "",
        "backup_sha256": "",
        "lock_path": rel_path(out_dir / f"{REPORT_STEM}.lock"),
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
            "identity_merge": False,
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
        "artifacts": {
            "report_json": rel_path(out_dir / f"{REPORT_STEM}.json"),
            "scorecard": rel_path(scorecard_path),
            "candidates_jsonl": rel_path(out_dir / "s209_manual_artifact_disposition_candidates.jsonl"),
            "rejected_jsonl": rel_path(out_dir / "s209_manual_artifact_disposition_rejected.jsonl"),
        },
    }
    if not candidates:
        report["decision"] = f"{REPORT_STEM}_blocked_no_candidates"
        return report
    if not execute:
        report["decision"] = f"{REPORT_STEM}_dry_run_ready"
        return report
    lock_path = out_dir / f"{REPORT_STEM}.lock"
    with s148.FileLock(lock_path, max_attempts=max_lock_attempts):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = out_dir / f"backup_before_{REPORT_STEM}_{stamp}.sqlite"
        shutil.copy2(db3_path, backup_path)
        report["backup_path"] = rel_path(backup_path)
        report["backup_sha256"] = s148.sha256_file(backup_path)
        conn = s148.connect_rw(db3_path, busy_timeout_ms=busy_timeout_ms)
        try:
            conn.execute("BEGIN IMMEDIATE")
            s181.ensure_schema(conn)
            stamp_iso = now_iso()
            for row in profile_rows_to_write.values():
                conn.execute(
                    """
                    INSERT INTO dj_identity_profile_disposition (
                      dj_id, disposition, reason_code, source_story_id,
                      source_ref_count, event_count, subject_present, created_at
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
                report["decision"] = f"{REPORT_STEM}_blocked_precommit_readback"
                return report
            conn.commit()
            postcommit = readback(conn, sorted(profile_rows_to_write))
            report["postcommit_readback"] = postcommit
            if not postcommit["ok"]:
                report["blocked_reasons"].append("postcommit_readback_failed_manual_restore_required")
                report["decision"] = f"{REPORT_STEM}_blocked_postcommit_readback"
                return report
            report["write_state"] = {
                "write_executed": True,
                "committed": True,
                "rollback_performed": False,
                "db3_profile_disposition_write": True,
            }
            report["decision"] = f"{REPORT_STEM}_committed_with_readback"
            return report
        except Exception as exc:  # noqa: BLE001
            try:
                conn.rollback()
                report["write_state"]["rollback_performed"] = True
            except sqlite3.Error:
                pass
            report["blocked_reasons"].append(f"{exc.__class__.__name__}:{exc}")
            report["decision"] = f"{REPORT_STEM}_blocked_exception"
            return report
        finally:
            conn.close()


def render_scorecard(report: dict[str, Any]) -> str:
    readback_payload = report.get("postcommit_readback") or report.get("precommit_readback") or {}
    lines = [
        "# Weekly Atlas Relation Identity Manual Artifact Disposition S209",
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
        "- Allows only strict band/collective artifacts and count/role lineup fragments.",
        "- Excludes aka/slash/stage-name variants and ambiguous collaboration aliases.",
        "- No DB2 projection, deploy/upload/review/release.",
        "",
        "## Artifacts",
    ]
    for key, value in report["artifacts"].items():
        lines.append(f"- `{key}`: `{value}`")
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blockers"])
        for reason in report["blocked_reasons"]:
            lines.append(f"- `{reason}`")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--busy-timeout-ms", type=int, default=5000)
    parser.add_argument("--max-lock-attempts", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_write(
        db3_path=args.db3,
        input_path=args.input,
        out_dir=args.out_dir,
        scorecard_path=args.scorecard,
        execute=args.execute,
        busy_timeout_ms=args.busy_timeout_ms,
        max_lock_attempts=args.max_lock_attempts,
    )
    atomic_write_json(args.out_dir / f"{REPORT_STEM}.json", report)
    atomic_write_text(args.out_dir / f"{REPORT_STEM}.md", render_scorecard(report))
    atomic_write_text(args.scorecard, render_scorecard(report))
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "candidate_group_count": report["candidate_group_count"],
                "candidate_profile_count": report["candidate_profile_count"],
                "committed": report["write_state"]["committed"],
                "out_dir": rel_path(args.out_dir),
            },
            ensure_ascii=False,
        )
    )
    if report["decision"].endswith("committed_with_readback") or report["decision"].endswith("dry_run_ready"):
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
