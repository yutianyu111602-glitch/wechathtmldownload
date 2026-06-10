#!/usr/bin/env python3
"""Run S193 DB3 identity batch from S192 local archive article evidence.

S193 consumes S192 report-local article artifacts, revalidates each relation
group against live DB3, and opens a guarded write gate only when local article
text covers every live profile by display/alias evidence. It does not fetch the
network, project DB2, deploy, upload, or print raw source URLs.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
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
from tools.stage7_rewrite.scripts import run_atlas_relation_source_archive_replay_s192 as s192


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S193"
REPORT_STEM = "atlas_relation_identity_archive_evidence_batch_s193"
SCHEMA_VERSION = f"{REPORT_STEM}.v1"

DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_INPUT = (
    REPORTS_ROOT
    / "atlas_relation_source_archive_replay_s192_20260602"
    / "s192_archive_article_ready_rows.jsonl"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_archive_evidence_batch_s193_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_ARCHIVE_EVIDENCE_BATCH_S193_20260602.md"

ALLOWED_REASONS = {"city_empty", "token_not_safe_ascii", "display_token_mismatch"}
TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
ASCII_ALNUM_RE = re.compile(r"[a-z0-9]", re.IGNORECASE)


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


def normalize_compact(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(ch for ch in normalized if unicodedata.category(ch)[0] in {"L", "N"})


def text_from_html(html_text: str) -> str:
    without_code = SCRIPT_STYLE_RE.sub(" ", html_text)
    without_tags = TAG_RE.sub(" ", without_code)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def html_path_for_row(row: dict[str, Any]) -> Path:
    bundle = Path(str(row.get("artifact_bundle_relpath") or ""))
    if not bundle.is_absolute():
        bundle = REPO_ROOT / bundle
    return bundle / "article.html"


def read_article_text(row: dict[str, Any]) -> tuple[str, list[str]]:
    blockers: list[str] = []
    path = html_path_for_row(row)
    if not path.exists():
        return "", ["article_html_artifact_missing"]
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return "", [f"article_html_read_failed:{exc.__class__.__name__}"]
    text = text_from_html(raw)
    if len(text) < 80:
        blockers.append("article_text_too_short")
    return text, blockers


def safe_alias_variants(value: Any) -> list[dict[str, str]]:
    raw = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not raw:
        return []
    compact = normalize_compact(raw)
    cjk_count = len(CJK_RE.findall(compact))
    ascii_count = len(ASCII_ALNUM_RE.findall(compact))
    if cjk_count >= 2 or ascii_count >= 3 or (cjk_count >= 1 and ascii_count >= 2):
        return [{"raw": raw, "compact": compact}]
    return []


def profile_alias_values(profile: dict[str, Any]) -> list[str]:
    values = [
        profile.get("display_name"),
        profile.get("normalized_name"),
        *s148.parse_aliases(profile.get("aliases_json")),
    ]
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        key = normalize_compact(text)
        if text and key and key not in seen:
            result.append(text)
            seen.add(key)
    return result


def match_profile_in_articles(profile: dict[str, Any], article_rows: list[dict[str, Any]]) -> dict[str, Any]:
    variants: list[dict[str, str]] = []
    for value in profile_alias_values(profile):
        variants.extend(safe_alias_variants(value))
    compact_articles = [
        {
            "article_uid": row.get("article_uid"),
            "source_ref_id": row.get("source_ref_id"),
            "resolved_article_source_ref_id": row.get("resolved_article_source_ref_id"),
            "source_account": row.get("source_account"),
            "title": row.get("title"),
            "post_date": row.get("post_date"),
            "html_artifact_ref_id": row.get("html_artifact_ref_id"),
            "text_compact": row.get("_text_compact") or "",
        }
        for row in article_rows
    ]
    hits: list[dict[str, Any]] = []
    for variant in variants:
        token = variant["compact"]
        if not token:
            continue
        for article in compact_articles:
            if token in article["text_compact"]:
                hits.append(
                    {
                        "alias": variant["raw"],
                        "alias_compact": token,
                        "article_uid": article["article_uid"],
                        "source_ref_id": article["source_ref_id"],
                        "resolved_article_source_ref_id": article["resolved_article_source_ref_id"],
                        "source_account": article["source_account"],
                        "title": article["title"],
                        "post_date": article["post_date"],
                        "html_artifact_ref_id": article["html_artifact_ref_id"],
                    }
                )
                break
    return {
        "dj_id": profile.get("dj_id"),
        "display_name": profile.get("display_name"),
        "safe_alias_count": len(variants),
        "matched": bool(hits),
        "hits": hits[:8],
    }


def group_archive_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[frozenset[str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        ids = frozenset(str(value) for value in row.get("dj_ids") or [] if str(value))
        if ids:
            grouped[ids].append(row)
    result: list[dict[str, Any]] = []
    for ids, members in grouped.items():
        result.append(
            {
                "dj_ids": sorted(ids),
                "group_ids": sorted({str(row.get("group_id") or "") for row in members if str(row.get("group_id") or "")}),
                "display_names": sorted({str(name) for row in members for name in (row.get("display_names") or []) if str(name)}),
                "rows": sorted(members, key=lambda row: (str(row.get("article_uid") or ""), str(row.get("source_ref_id") or ""))),
            }
        )
    return sorted(result, key=lambda item: (len(item["dj_ids"]), item["group_ids"], item["dj_ids"]))


def group_lookup(conn: sqlite3.Connection) -> dict[frozenset[str], tuple[str, str, list[dict[str, Any]]]]:
    lookup: dict[frozenset[str], tuple[str, str, list[dict[str, Any]]]] = {}
    for (city, token), group in s164.grouped_profile_rows(conn).items():
        ids = frozenset(str(row["dj_id"]) for row in group)
        if len(ids) > 1:
            lookup[ids] = (city, token, group)
    return lookup


def archive_evidence_for_group(group_row: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    blockers: list[str] = []
    article_rows: list[dict[str, Any]] = []
    for row in group_row["rows"]:
        if row.get("article_artifact_ready") is not True:
            blockers.append("s192_row_not_article_ready")
            continue
        text, text_blockers = read_article_text(row)
        blockers.extend(text_blockers)
        if text:
            article_rows.append({**row, "_text_compact": normalize_compact(text)})
    source_accounts = sorted({str(row.get("source_account") or "") for row in article_rows if str(row.get("source_account") or "")})
    article_uids = sorted({str(row.get("article_uid") or "") for row in article_rows if str(row.get("article_uid") or "")})
    evidence = {
        "article_ready_row_count": len(article_rows),
        "article_uid_count": len(article_uids),
        "article_uids_sample": article_uids[:12],
        "source_accounts": source_accounts,
        "source_account_count": len(source_accounts),
        "titles_sample": sorted({str(row.get("title") or "") for row in article_rows if str(row.get("title") or "")})[:12],
        "post_dates_sample": sorted({str(row.get("post_date") or "") for row in article_rows if str(row.get("post_date") or "")})[:12],
        "html_artifact_ref_ids_sample": sorted({str(row.get("html_artifact_ref_id") or "") for row in article_rows if str(row.get("html_artifact_ref_id") or "")})[:12],
        "raw_source_url_emitted": False,
        "archive_path_emitted": False,
    }
    if not article_rows:
        blockers.append("no_article_text_rows")
    if len(source_accounts) != 1:
        blockers.append("source_account_not_single")
    return evidence, sorted(set(blockers)), article_rows


def build_live_candidate(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    lookup: dict[frozenset[str], tuple[str, str, list[dict[str, Any]]]],
) -> tuple[dict[str, Any] | None, list[str]]:
    blockers: list[str] = []
    dj_ids = [str(dj_id) for dj_id in row.get("dj_ids") or [] if str(dj_id)]
    if len(dj_ids) != 2:
        blockers.append("not_two_profiles")
    live = lookup.get(frozenset(dj_ids))
    if not live:
        return None, sorted(set([*blockers, "live_group_not_found_or_already_changed"]))
    city, token, group = live
    classified = s164.classify_row(group, city=city, token=token, conn=conn)
    values = [*classified["display_names"], *classified["normalized_names"], classified["identity_token"]]
    compacts = s167.compact_set(values)
    risk_reasons = [*s171.s171_risk_reasons(values)]
    if s167.has_enhanced_risk(values):
        risk_reasons.append("enhanced_risk_or_collaboration_marker")
    if len(group) != 2:
        blockers.append("live_group_not_two_profiles")
    if not set(classified.get("s159_rejection_reasons") or []) <= ALLOWED_REASONS:
        blockers.append("rejection_reasons_not_allowed")
    if len(compacts) != 1:
        blockers.append("unicode_compact_not_equivalent")
    compact_token = next(iter(compacts)) if compacts else ""
    if len(compact_token) < 3 and not CJK_RE.search(compact_token):
        blockers.append("compact_token_too_short_for_archive_gate")
    if risk_reasons:
        blockers.append("s171_or_enhanced_risk_marker")

    archive_evidence, archive_blockers, article_rows = archive_evidence_for_group(row)
    blockers.extend(archive_blockers)
    match_rows = [match_profile_in_articles(profile, article_rows) for profile in group]
    if not all(item.get("matched") for item in match_rows):
        blockers.append("article_alias_coverage_incomplete")
    if any(int(item.get("safe_alias_count") or 0) <= 0 for item in match_rows):
        blockers.append("profile_has_no_safe_alias_for_archive_gate")

    candidate = s159.build_candidate(city, token, group)
    candidate["prewrite_row_id"] = f"s193:{s159.group_hash(city, token, sorted(dj_ids))}"
    candidate["s192_group_ids"] = row.get("group_ids") or []
    candidate["s192_display_names"] = row.get("display_names") or []
    candidate["s159_rejection_reasons_before_s193"] = classified.get("s159_rejection_reasons") or []
    candidate["unicode_compact_token"] = compact_token
    candidate["input_city_values"] = [str(item.get("city_primary") or "") for item in group]
    candidate["city_policy"] = "preserve_non_empty_city_or_allow_empty_when_archive_article_coverage_complete"
    candidate["s193_risk_reasons"] = sorted(set(risk_reasons))
    candidate["s193_archive_evidence"] = {
        **archive_evidence,
        "profile_alias_coverage": match_rows,
        "coverage_complete": bool(match_rows) and all(item.get("matched") for item in match_rows),
    }
    candidate["safety_basis"] = [
        "s192_exact_local_archive_article_artifact",
        "two_profiles_only",
        "unicode_compact_display_and_normalized_names_equivalent",
        "subject_present_for_all_ids",
        "source_ref_backed_event_for_all_ids",
        "single_source_account_in_archive_artifacts",
        "each_live_profile_has_safe_alias_hit_in_article_text",
        "collective_label_lineup_role_bio_sentence_and_collaboration_markers_absent",
        "raw_source_url_and_archive_path_not_emitted",
    ]
    if not s169.profile_evidence_ok(candidate):
        blockers.append("profile_source_ref_or_subject_evidence_missing")
    return (candidate if not blockers else None), sorted(set(blockers))


def live_candidates(conn: sqlite3.Connection, input_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    rows = [row for row in s192.read_jsonl(input_path) if row.get("article_artifact_ready") is True]
    grouped_rows = group_archive_rows(rows)
    lookup = group_lookup(conn)
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in grouped_rows:
        candidate, blockers = build_live_candidate(conn, row, lookup)
        if blockers or not candidate:
            rejected.append(
                {
                    "dj_ids": row.get("dj_ids") or [],
                    "group_ids": row.get("group_ids") or [],
                    "display_names": row.get("display_names") or [],
                    "article_ready_row_count": len(row.get("rows") or []),
                    "s193_blockers": blockers,
                }
            )
            continue
        candidates.append(candidate)
    state = {
        "input_article_ready_row_count": len(rows),
        "input_group_count": len(grouped_rows),
        "archive_evidence_candidate_count": len(candidates),
        "rejected_count": len(rejected),
        "rejection_reason_counts": dict(Counter(reason for row in rejected for reason in row.get("s193_blockers") or [])),
        "table_counts": s148.table_counts(conn),
    }
    return sorted(candidates, key=lambda item: tuple(item["risk_tuple_live"])), rejected, state


def validate_s193_prewrite(conn: sqlite3.Connection, selected: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if selected.get("city_policy") != "preserve_non_empty_city_or_allow_empty_when_archive_article_coverage_complete":
        blockers.append("city_policy_missing")
    if not set(selected.get("s159_rejection_reasons_before_s193") or []) <= ALLOWED_REASONS:
        blockers.append("not_allowed_s159_rejection_reasons")
    if len(selected.get("all_dj_ids") or []) != 2:
        blockers.append("not_two_profiles")
    if not s169.profile_evidence_ok(selected):
        blockers.append("profile_source_ref_or_subject_evidence_missing")
    values = [
        *list(selected.get("display_names") or []),
        selected.get("identity_token", ""),
        *((row.get("normalized_name") for row in selected.get("merge_profiles", []) or [])),
        ((selected.get("canonical_profile") or {}).get("normalized_name")),
    ]
    compacts = s167.compact_set(values)
    if len(compacts) != 1:
        blockers.append("unicode_compact_not_equivalent")
    compact_token = next(iter(compacts)) if compacts else ""
    if len(compact_token) < 3 and not CJK_RE.search(compact_token):
        blockers.append("compact_token_too_short_for_archive_gate")
    if s171.s171_risk_reasons(values) or s167.has_enhanced_risk(values):
        blockers.append("s171_or_enhanced_risk_marker")
    evidence = selected.get("s193_archive_evidence") or {}
    if evidence.get("coverage_complete") is not True:
        blockers.append("article_alias_coverage_incomplete")
    if int(evidence.get("article_ready_row_count") or 0) <= 0:
        blockers.append("no_article_text_rows")
    if int(evidence.get("source_account_count") or 0) != 1:
        blockers.append("source_account_not_single")
    coverage = evidence.get("profile_alias_coverage") or []
    if len(coverage) != len(selected.get("all_dj_ids") or []):
        blockers.append("profile_alias_coverage_count_mismatch")
    if any(not item.get("matched") for item in coverage):
        blockers.append("article_alias_coverage_incomplete")
    blockers.extend(s159.redirect_conflicts(conn, selected))
    blockers.extend(s148.validate_prewrite_state(conn, selected))
    return sorted(set(blockers))


def execute_selected(
    *,
    db3_path: Path,
    out_dir: Path,
    report_path: Path,
    selected: dict[str, Any],
    story_label: str,
    busy_timeout_ms: int,
    max_lock_attempts: int,
    shared_backup: dict[str, str] | None = None,
) -> dict[str, Any]:
    lock_path = out_dir / f"{REPORT_STEM}_{story_label}.lock"
    result: dict[str, Any] = {
        "execute_requested": True,
        "write_executed": False,
        "committed": False,
        "lock_path": rel_path(lock_path),
        "backup_path": "",
        "backup_sha256": "",
        "rollback_performed": False,
        "blocked_reasons": [],
        "redirect_readback": {},
    }
    with s148.FileLock(lock_path, max_attempts=max_lock_attempts):
        if shared_backup:
            result["backup_path"] = shared_backup["path"]
            result["backup_sha256"] = shared_backup["sha256"]
        else:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = out_dir / f"backup_before_relation_identity_archive_evidence_{story_label}_{stamp}.sqlite"
            shutil.copy2(db3_path, backup_path)
            result["backup_path"] = rel_path(backup_path)
            result["backup_sha256"] = s148.sha256_file(backup_path)
        conn = s148.connect_rw(db3_path, busy_timeout_ms=busy_timeout_ms)
        try:
            pre_blockers = validate_s193_prewrite(conn, selected)
            if pre_blockers:
                result["blocked_reasons"].extend(pre_blockers)
                return result
            before = s148.canary_snapshot(conn, selected)
            expected_counts = s148.expected_table_counts(conn, selected)
            canonical_before = next((row for row in before["profile_rows"] if row.get("dj_id") == selected["canonical_dj_id"]), None)
            conn.execute("BEGIN IMMEDIATE")
            write_stats = s148.apply_canary_merge(conn, selected)
            precommit = s167.postwrite_readback_unicode_anchor(conn, selected, expected_counts, canonical_before)
            s159.insert_redirect_rows(conn, selected, story_label=story_label, report_path=report_path)
            redirect_precommit = s159.redirect_readback(conn, selected)
            result["prewrite_snapshot"] = before
            result["write_stats"] = write_stats
            result["precommit_readback"] = precommit
            result["redirect_readback"] = redirect_precommit
            if not precommit["ok"] or not redirect_precommit["ok"]:
                conn.rollback()
                result["rollback_performed"] = True
                result["blocked_reasons"].append("precommit_readback_failed")
                return result
            conn.commit()
            postcommit = s167.postwrite_readback_unicode_anchor(conn, selected, expected_counts, canonical_before)
            redirect_postcommit = s159.redirect_readback(conn, selected)
            result["postcommit_readback"] = postcommit
            result["redirect_postcommit_readback"] = redirect_postcommit
            if not postcommit["ok"] or not redirect_postcommit["ok"]:
                result["blocked_reasons"].append("postcommit_readback_failed_manual_restore_required")
                return result
            result["write_executed"] = True
            result["committed"] = True
            return result
        except Exception as exc:  # noqa: BLE001
            try:
                conn.rollback()
                result["rollback_performed"] = True
            except sqlite3.Error:
                pass
            result["blocked_reasons"].append(f"{exc.__class__.__name__}:{exc}")
            return result
        finally:
            conn.close()


def run_batch(
    *,
    db3_path: Path,
    input_path: Path,
    out_dir: Path,
    scorecard_path: Path,
    max_count: int,
    execute: bool,
    busy_timeout_ms: int,
    max_lock_attempts: int,
    batch_backup: bool,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{REPORT_STEM}.json"
    shared_backup: dict[str, str] | None = None
    if execute and batch_backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = out_dir / f"backup_before_relation_identity_archive_evidence_batch_s193_{stamp}.sqlite"
        shutil.copy2(db3_path, backup_path)
        shared_backup = {"path": rel_path(backup_path), "sha256": s148.sha256_file(backup_path)}

    conn = sqlite3.connect(f"file:{db3_path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        initial_candidates, initial_rejected, initial_state = live_candidates(conn, input_path)
    finally:
        conn.close()

    iterations: list[dict[str, Any]] = []
    stopped_reason = ""
    for index in range(max_count):
        conn = sqlite3.connect(f"file:{db3_path.resolve().as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            queue, rejected, live_state = live_candidates(conn, input_path)
        finally:
            conn.close()
        if not queue:
            stopped_reason = "eligible_queue_empty"
            break
        selected = queue[0]
        story_label = f"s193_{index + 1:03d}"
        iteration: dict[str, Any] = {
            "index": index + 1,
            "story_label": story_label,
            "selected_group_id": selected["group_id"],
            "selected_prewrite_row_id": selected["prewrite_row_id"],
            "canonical_dj_id": selected["canonical_dj_id"],
            "merge_dj_ids": selected["merge_dj_ids"],
            "display_names": selected["display_names"],
            "s193_archive_evidence": selected["s193_archive_evidence"],
            "pre_execution_queue_count": len(queue),
            "pre_execution_rejected_count": len(rejected),
            "pre_execution_live_state": live_state,
        }
        if not execute:
            iteration["execution"] = {"execute_requested": False, "write_executed": False, "committed": False}
            iterations.append(iteration)
            stopped_reason = "dry_run_only"
            break
        execution = execute_selected(
            db3_path=db3_path,
            out_dir=out_dir,
            report_path=report_path,
            selected=selected,
            story_label=story_label,
            busy_timeout_ms=busy_timeout_ms,
            max_lock_attempts=max_lock_attempts,
            shared_backup=shared_backup,
        )
        iteration["execution"] = execution
        iterations.append(iteration)
        if not execution.get("committed"):
            stopped_reason = "write_blocked_or_readback_failed"
            break
    else:
        stopped_reason = "max_count_reached"

    conn = sqlite3.connect(f"file:{db3_path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        final_candidates, final_rejected, final_state = live_candidates(conn, input_path)
    finally:
        conn.close()

    committed_count = sum(1 for item in iterations if item.get("execution", {}).get("committed"))
    decision = (
        f"{REPORT_STEM}_committed_with_readback"
        if execute and committed_count > 0 and not any(not item.get("execution", {}).get("committed") for item in iterations)
        else f"{REPORT_STEM}_dry_run_ready"
        if not execute and initial_candidates
        else f"{REPORT_STEM}_blocked_no_candidates"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "current_story_id": CURRENT_STORY_ID,
        "generated_at": now_iso(),
        "decision": decision,
        "execute_requested": execute,
        "input_path": rel_path(input_path),
        "initial_state": initial_state,
        "final_state": final_state,
        "initial_candidate_sample": initial_candidates[:10],
        "initial_rejected_sample": initial_rejected[:20],
        "final_candidate_sample": final_candidates[:10],
        "iterations": iterations,
        "committed_count": committed_count,
        "stopped_reason": stopped_reason,
        "backup_path": shared_backup["path"] if shared_backup else "",
        "backup_sha256": shared_backup["sha256"] if shared_backup else "",
        "safety": {
            "database_mutations": bool(execute and committed_count),
            "db3_identity_merge_only": True,
            "db2_projection": False,
            "release_rebuild": False,
            "deploy_upload_review": False,
            "network_fetch": False,
            "provider_or_llm_call": False,
            "secret_read": False,
            "raw_source_url_emitted": False,
            "archive_path_emitted": False,
            "single_writer_lock": True,
            "backup_before_write": bool(shared_backup or not execute),
            "transaction_and_readback": True,
        },
        "artifacts": {
            "report_json": rel_path(report_path),
            "scorecard": rel_path(scorecard_path),
            "initial_candidates_jsonl": rel_path(out_dir / "s193_initial_candidates.jsonl"),
            "initial_rejected_jsonl": rel_path(out_dir / "s193_initial_rejected.jsonl"),
            "final_candidates_jsonl": rel_path(out_dir / "s193_final_candidates.jsonl"),
            "final_rejected_jsonl": rel_path(out_dir / "s193_final_rejected.jsonl"),
        },
    }
    write_jsonl(out_dir / "s193_initial_candidates.jsonl", initial_candidates)
    write_jsonl(out_dir / "s193_initial_rejected.jsonl", initial_rejected)
    write_jsonl(out_dir / "s193_final_candidates.jsonl", final_candidates)
    write_jsonl(out_dir / "s193_final_rejected.jsonl", final_rejected)
    atomic_write_json(report_path, report)
    write_scorecard(scorecard_path, report)
    return report


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    initial = report["initial_state"]
    final = report["final_state"]
    lines = [
        "# Weekly Atlas Relation Identity Archive Evidence Batch S193",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Input article-ready rows: `{initial['input_article_ready_row_count']}`",
        f"- Initial candidates: `{initial['archive_evidence_candidate_count']}`",
        f"- Committed: `{report['committed_count']}`",
        f"- Final candidates: `{final['archive_evidence_candidate_count']}`",
        f"- Stopped reason: `{report['stopped_reason']}`",
        "",
        "## Boundaries",
        "",
        "- DB3 identity merge only, with single-writer lock, backup, transaction, redirect, and postwrite readback.",
        "- Consumes S192 report-local local archive article artifacts; no network fetch, no DB2 projection, no deploy/upload/review, no raw URL/path output.",
        "",
        "## Rejection Counts",
        "",
    ]
    for key, value in sorted((initial.get("rejection_reason_counts") or {}).items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Artifacts"])
    for key, value in report["artifacts"].items():
        lines.append(f"- `{key}`: `{value}`")
    if report.get("backup_path"):
        lines.append(f"- `backup`: `{report['backup_path']}` sha256 `{report['backup_sha256']}`")
    atomic_write_text(path, "\n".join(lines) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--max-count", type=int, default=20)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--busy-timeout-ms", type=int, default=5000)
    parser.add_argument("--max-lock-attempts", type=int, default=20)
    parser.add_argument("--no-batch-backup", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_batch(
        db3_path=args.db3,
        input_path=args.input,
        out_dir=args.out_dir,
        scorecard_path=args.scorecard,
        max_count=args.max_count,
        execute=args.execute,
        busy_timeout_ms=args.busy_timeout_ms,
        max_lock_attempts=args.max_lock_attempts,
        batch_backup=not args.no_batch_backup,
    )
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "committed_count": report["committed_count"],
                "initial_candidates": report["initial_state"]["archive_evidence_candidate_count"],
                "final_candidates": report["final_state"]["archive_evidence_candidate_count"],
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
