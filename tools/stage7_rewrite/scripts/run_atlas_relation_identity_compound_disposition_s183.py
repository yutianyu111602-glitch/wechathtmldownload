#!/usr/bin/env python3
"""Write DB3 dispositions for high-confidence compound / role artifacts.

S183 rebuilds the live same-normalized blocker workbench after S181
dispositions, then optionally closes only the high-confidence non-person subset:
ampersand/b2b/feat/vs compounds, plural-DJs/guest labels, and DJ role artifacts.
Ambiguous slash aliases, spaced-X names, parenthetical aliases, source/provider
gaps, and venue-only clusters remain explicit workbench tasks.
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

from tools.stage7_rewrite.scripts import audit_atlas_relation_field_integrity as audit
from tools.stage7_rewrite.scripts import build_atlas_relation_identity_complex_classifier_s164 as s164
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_db3_canary_s148 as s148
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_non_person_disposition_s181 as s181
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_multivenue_batch_s169 as s169
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_singlevenue_batch_s171 as s171
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_source_anchor_batch_s167 as s167


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S183"
SCHEMA_VERSION = "atlas_relation_identity_compound_disposition_s183.v1"
DISPOSITION = "non_person_compound_or_role_artifact"

DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_compound_disposition_s183_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_COMPOUND_DISPOSITION_S183_20260602.md"

AMPERSAND_RE = re.compile(r"&")
B2B_FEAT_VS_RE = re.compile(r"(\bb2b\b|back\s*to\s*back|feat\.?|featuring|\bvs\b)", re.I)
ROLE_ARTIFACT_RE = re.compile(
    r"(\bdjs\b|\bdj's\b|\bguests?\b|special\s*guest|local\s+dj|"
    r"dj\s*/\s*producer|dj\s+producer|dj\s*[,.]\s*promoter|dj\s*/\s*promoter|"
    r"promoter|贝斯手|吉他手|鼓手|主唱|主理人)",
    re.I,
)


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


def display_has_high_confidence_compound_marker(value: str) -> bool:
    return bool(AMPERSAND_RE.search(value) or B2B_FEAT_VS_RE.search(value) or ROLE_ARTIFACT_RE.search(value))


def high_confidence_compound_disposition(displays: list[str]) -> tuple[bool, str]:
    text = " ".join(displays)
    if ROLE_ARTIFACT_RE.search(text):
        return True, "role_plural_or_guest_marker"
    if B2B_FEAT_VS_RE.search(text):
        return True, "b2b_feat_vs_marker"
    if displays and all(AMPERSAND_RE.search(display) for display in displays):
        return True, "ampersand_compound_all_variants"
    return False, ""


def exact_same_normalized_group(city: str, token: str, group: list[dict[str, Any]]) -> bool:
    normalized_values = sorted({s164.s159.normalized_token(row.get("normalized_name")) for row in group if row.get("normalized_name")})
    return len(normalized_values) == 1 and normalized_values[0] == token


def accepted_group_disposition(ids: list[str], profile_dispositions: dict[str, dict[str, str]]) -> bool:
    dispositions = [profile_dispositions.get(dj_id, {}) for dj_id in ids]
    return bool(dispositions) and all(audit.accepted_same_normalized_disposition(row) for row in dispositions)


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


def classify_remaining_lane(
    classified: dict[str, Any],
    *,
    risk_reasons: list[str],
    compacts: set[str],
    marker_reason: str,
    evidence_ok: bool,
) -> str:
    row_count = int(classified.get("row_count") or 0)
    has_source_event = int(classified.get("common_source_ref_count") or 0) > 0 or int(classified.get("common_event_count") or 0) > 0
    has_venue = int(classified.get("common_venue_count") or 0) > 0
    reasons = set(classified.get("s159_rejection_reasons") or [])

    if marker_reason and evidence_ok:
        return "compound_disposition_write_candidate"
    if marker_reason and not evidence_ok:
        return "compound_disposition_evidence_gap"
    if "collaboration_marker" in risk_reasons or "separator_or_collaboration_marker_present" in reasons:
        return "compound_or_alias_review"
    if risk_reasons:
        return "risk_disposition_review"
    if row_count == 2 and len(compacts) == 1 and has_source_event:
        return "pair_source_event_manual_review"
    if row_count == 2 and len(compacts) == 1 and has_venue:
        return "pair_provider_crosscheck"
    if row_count == 2 and len(compacts) == 1:
        return "source_provider_acquisition_no_anchor"
    if row_count >= 3 and len(compacts) == 1 and has_source_event:
        return "cluster_source_event_chain_review"
    if row_count >= 3 and len(compacts) == 1 and has_venue:
        return "cluster_provider_crosscheck"
    if row_count >= 3:
        return "cluster_chain_review"
    return "other_manual_review"


def task_type_for_lane(lane: str) -> str:
    if lane == "compound_disposition_write_candidate":
        return "write_non_person_compound_disposition"
    if "acquisition" in lane:
        return "source_provider_acquisition"
    if "provider_crosscheck" in lane:
        return "provider_crosscheck"
    if "compound_or_alias" in lane:
        return "alias_vs_compound_review"
    if "cluster" in lane:
        return "cluster_chain_review"
    return "manual_disposition_review"


def collect_workbench(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    profile_dispositions = audit.load_profile_dispositions(conn)
    candidates: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    dispositioned_groups: list[dict[str, Any]] = []
    for (city, token), group in sorted(s164.grouped_profile_rows(conn).items()):
        ids = sorted({str(row["dj_id"]) for row in group})
        if len(ids) <= 1 or not exact_same_normalized_group(city, token, group):
            continue
        if accepted_group_disposition(ids, profile_dispositions):
            dispositioned_groups.append({"group_id": f"{city}::{token}", "dj_ids": ids})
            continue
        classified = s164.classify_row(group, city=city, token=token, conn=conn)
        values = [*classified["display_names"], *classified["normalized_names"], classified["identity_token"]]
        risk_reasons = s171.s171_risk_reasons(values)
        compacts = s167.compact_set(values)
        candidate = s164.s159.build_candidate(city, token, group)
        evidence_ok = s169.profile_evidence_ok(candidate)
        marker_ok, marker_reason = high_confidence_compound_disposition(classified["display_names"])
        lane = classify_remaining_lane(
            classified,
            risk_reasons=risk_reasons,
            compacts=compacts,
            marker_reason=marker_reason if marker_ok else "",
            evidence_ok=evidence_ok,
        )
        row = {
            **classified,
            "current_story_id": CURRENT_STORY_ID,
            "s183_lane": lane,
            "s183_task_type": task_type_for_lane(lane),
            "s183_risk_reasons": risk_reasons,
            "unicode_compact_values": sorted(compacts),
            "profile_evidence_ok": evidence_ok,
            "compound_marker_reason": marker_reason if marker_ok else "",
            "production_disposition_candidate": lane == "compound_disposition_write_candidate",
        }
        rows.append(row)
        if lane == "compound_disposition_write_candidate":
            candidate["prewrite_row_id"] = f"s183:{s164.s159.group_hash(city, token, ids)}"
            candidate["current_story_id"] = CURRENT_STORY_ID
            candidate["s183_group_row"] = row
            candidate["disposition"] = DISPOSITION
            candidate["reason_code"] = marker_reason
            candidate["profile_disposition_rows"] = disposition_rows_for_candidate(candidate, marker_reason)
            candidate["safety_basis"] = [
                "whole_same_normalized_group_not_already_dispositioned",
                "high_confidence_compound_or_role_marker",
                "subject_present_for_all_ids",
                "source_ref_backed_event_for_all_ids",
                "writes_disposition_table_only",
                "ambiguous_slash_parenthetical_or_spaced_x_aliases_excluded",
                "audit_excludes_only_when_whole_same_normalized_group_is_evidence_backed_disposition",
            ]
            candidates.append(candidate)
    return candidates, rows, {"accepted_existing_disposition_groups": dispositioned_groups}


def write_workbench_files(out_dir: Path, *, candidates: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, str]:
    tasks = [
        {
            "task_id": f"s183:{row['s183_lane']}:{index + 1:04d}",
            "lane": row["s183_lane"],
            "task_type": row["s183_task_type"],
            "group_id": row["group_id"],
            "dj_ids": row["dj_ids"],
            "display_names": row["display_names"],
            "next_action": row["s183_task_type"],
            "production_disposition_candidate": row["production_disposition_candidate"],
        }
        for index, row in enumerate(rows)
    ]
    acquisition_tasks = [task for task in tasks if task["task_type"] == "source_provider_acquisition"]
    provider_tasks = [task for task in tasks if task["task_type"] == "provider_crosscheck"]
    compound_review_tasks = [task for task in tasks if task["task_type"] == "alias_vs_compound_review"]
    artifacts = {
        "remaining_rows_jsonl": rel_path(out_dir / "compound_disposition_remaining_rows_s183.jsonl"),
        "compound_candidates_jsonl": rel_path(out_dir / "compound_disposition_candidates_s183.jsonl"),
        "tasks_jsonl": rel_path(out_dir / "compound_disposition_tasks_s183.jsonl"),
        "source_provider_acquisition_tasks_jsonl": rel_path(out_dir / "source_provider_acquisition_tasks_s183.jsonl"),
        "provider_crosscheck_tasks_jsonl": rel_path(out_dir / "provider_crosscheck_tasks_s183.jsonl"),
        "compound_or_alias_review_tasks_jsonl": rel_path(out_dir / "compound_or_alias_review_tasks_s183.jsonl"),
    }
    write_jsonl(out_dir / "compound_disposition_remaining_rows_s183.jsonl", rows)
    write_jsonl(out_dir / "compound_disposition_candidates_s183.jsonl", candidates)
    write_jsonl(out_dir / "compound_disposition_tasks_s183.jsonl", tasks)
    write_jsonl(out_dir / "source_provider_acquisition_tasks_s183.jsonl", acquisition_tasks)
    write_jsonl(out_dir / "provider_crosscheck_tasks_s183.jsonl", provider_tasks)
    write_jsonl(out_dir / "compound_or_alias_review_tasks_s183.jsonl", compound_review_tasks)
    return artifacts


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
    out_dir: Path,
    execute: bool,
    busy_timeout_ms: int,
    max_lock_attempts: int,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = s164.s159.connect_ro(db3_path)
    try:
        candidates, rows, extra = collect_workbench(conn)
        initial_table_counts = s148.table_counts(conn)
    finally:
        conn.close()

    artifacts = write_workbench_files(out_dir, candidates=candidates, rows=rows)
    lane_counts = Counter(row["s183_lane"] for row in rows)
    task_type_counts = Counter(row["s183_task_type"] for row in rows)
    profile_rows_to_write = {
        row["dj_id"]: row
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
        "initial_state": {
            "remaining_same_normalized_group_count": len(rows),
            "existing_dispositioned_group_count": len(extra["accepted_existing_disposition_groups"]),
            "compound_disposition_candidate_group_count": len(candidates),
            "compound_disposition_candidate_profile_count": len(profile_rows_to_write),
            "lane_counts": dict(sorted(lane_counts.items())),
            "task_type_counts": dict(sorted(task_type_counts.items())),
            "table_counts": initial_table_counts,
            "candidate_sample": candidates[:30],
            "remaining_sample": rows[:30],
        },
        "backup_path": "",
        "backup_sha256": "",
        "lock_path": rel_path(out_dir / "atlas_relation_identity_compound_disposition_s183.lock"),
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
        report["decision"] = "atlas_relation_identity_compound_disposition_s183_blocked_no_candidates"
        return report
    if not execute:
        report["decision"] = "atlas_relation_identity_compound_disposition_s183_dry_run_ready"
        return report

    lock_path = out_dir / "atlas_relation_identity_compound_disposition_s183.lock"
    with s148.FileLock(lock_path, max_attempts=max_lock_attempts):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = out_dir / f"backup_before_relation_identity_compound_disposition_s183_{stamp}.sqlite"
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
                report["decision"] = "atlas_relation_identity_compound_disposition_s183_blocked_precommit_readback"
                return report
            conn.commit()
            postcommit = readback(conn, sorted(profile_rows_to_write))
            report["postcommit_readback"] = postcommit
            if not postcommit["ok"]:
                report["blocked_reasons"].append("postcommit_readback_failed_manual_restore_required")
                report["decision"] = "atlas_relation_identity_compound_disposition_s183_blocked_postcommit_readback"
                return report
            report["write_state"] = {
                "write_executed": True,
                "committed": True,
                "rollback_performed": False,
                "db3_profile_disposition_write": True,
            }
            report["decision"] = "atlas_relation_identity_compound_disposition_s183_committed_with_readback"
            return report
        except Exception as exc:  # noqa: BLE001
            try:
                conn.rollback()
                report["write_state"]["rollback_performed"] = True
            except sqlite3.Error:
                pass
            report["blocked_reasons"].append(f"{exc.__class__.__name__}:{exc}")
            report["decision"] = "atlas_relation_identity_compound_disposition_s183_blocked_exception"
            return report
        finally:
            conn.close()


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    state = report["initial_state"]
    lines = [
        "# Weekly Atlas Relation Identity Compound Disposition S183",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Execute requested: `{str(report['execute_requested']).lower()}`",
        f"- Remaining same-normalized groups before S183 write: `{state['remaining_same_normalized_group_count']}`",
        f"- Existing dispositioned groups carried forward: `{state['existing_dispositioned_group_count']}`",
        f"- Compound disposition candidate groups: `{state['compound_disposition_candidate_group_count']}`",
        f"- Compound disposition candidate profiles: `{state['compound_disposition_candidate_profile_count']}`",
        f"- Backup: `{report.get('backup_path', '')}`",
        f"- Backup sha256: `{report.get('backup_sha256', '')}`",
        "",
        "## Lane Counts",
        "",
    ]
    for lane, count in sorted(state["lane_counts"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- `{lane}`: `{count}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Writes only DB3 `dj_identity_profile_disposition` rows when `--execute` is set.",
            "- No profile fields, relation tables, DB1, DB2, release package, deploy, upload, review, provider/model calls, secrets, service restart, or broad disk scan.",
            "- Ambiguous slash aliases, spaced-X names, parenthetical aliases, source/provider gaps, and venue-only clusters remain active tasks.",
            "",
        ]
    )
    atomic_write_text(path, "\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run S183 compound disposition workbench/write gate")
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--busy-timeout-ms", type=int, default=5000)
    parser.add_argument("--max-lock-attempts", type=int, default=5)
    args = parser.parse_args()

    report = run_write(
        db3_path=args.db3,
        out_dir=args.out_dir,
        execute=args.execute,
        busy_timeout_ms=args.busy_timeout_ms,
        max_lock_attempts=args.max_lock_attempts,
    )
    report_path = args.out_dir / "atlas_relation_identity_compound_disposition_s183.json"
    markdown_path = args.out_dir / "atlas_relation_identity_compound_disposition_s183.md"
    atomic_write_json(report_path, report)
    write_markdown(markdown_path, report)
    write_markdown(args.scorecard, report)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "execute_requested": report["execute_requested"],
                "remaining_same_normalized_groups": report["initial_state"]["remaining_same_normalized_group_count"],
                "candidate_groups": report["initial_state"]["compound_disposition_candidate_group_count"],
                "candidate_profiles": report["initial_state"]["compound_disposition_candidate_profile_count"],
                "postcommit_ok": bool((report.get("postcommit_readback") or {}).get("ok")),
                "json": rel_path(report_path),
                "markdown": rel_path(markdown_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not report["blocked_reasons"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
