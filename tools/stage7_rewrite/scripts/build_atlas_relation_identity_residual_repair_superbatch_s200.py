#!/usr/bin/env python3
"""Build S200 residual repair superbatch queues after S198/S199.

S200 consumes the fresh S199 relation identity queue and turns the remaining
368 blockers into executable repair lanes. It is report-only: no network fetch,
no DB1/DB2/DB3 mutation, and no raw source URLs or archive paths are emitted.
The main output is a P0 exact-local-archive queue for S201 plus source/provider
and manual disposition work orders for the remaining rows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.scripts import build_atlas_relation_external_acquisition_queue_s190 as s190
from tools.stage7_rewrite.scripts import build_atlas_relation_identity_source_provider_acquisition_s185 as s185
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_provider_strict_cluster_batch_s198 as s198
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_source_anchor_batch_s167 as s167


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S200"
REPORT_STEM = "atlas_relation_identity_residual_repair_superbatch_s200"
SCHEMA_VERSION = f"{REPORT_STEM}.v1"

DEFAULT_S199_DIR = REPORTS_ROOT / "atlas_relation_identity_source_provider_acquisition_s199_after_s198_full_20260602"
DEFAULT_SOURCE_URL_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_source_url_recovery_139123_candidate"
    / "atlas_source_url_recovery.sqlite"
)
DEFAULT_ALLOWED_ARCHIVE_ROOT = Path(r"D:\downstream_results\stage7_rewrite\longrun\WHERE_TO_RAVE_WECHAT_SYNC_20260508")
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_residual_repair_superbatch_s200_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_RESIDUAL_REPAIR_SUPERBATCH_S200_20260602.md"

RAW_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
RAW_ARCHIVE_PATH_RE = re.compile(r"(?i)(?:\b[A-Z]:\\[^\"'\n\r]+|/mnt/[a-z](?:/[^\"'\n\r]*)?)")
SECRET_LIKE_RE = re.compile(
    r"("
    r"cookie\s*[:=]\s*[\"']?[^\"'\s]{8,}|"
    r"authorization\s*[:=]\s*[\"']?[^\"'\s]{8,}|"
    r"x-auth-key\s*[:=]\s*[\"']?[^\"'\s]{8,}|"
    r"api[_-]?key\s*[:=]\s*[\"']?[^\"'\s]{8,}|"
    r"secret\s*[:=]\s*[\"']?[^\"'\s]{8,}|"
    r"bearer\s+[a-z0-9._-]{16,}"
    r")",
    re.I,
)
AKA_RE = re.compile(r"(\ba\.?\s*k\.?\s*a\.?\b|\baka\b|又名|别名)", re.I)
DJ_PREFIX_RE = re.compile(r"(^|\s|[\"'“”‘’])dj\s*", re.I)
ROLE_OR_COMPOUND_RE = re.compile(r"(\bb2b\b|feat\.?|featuring|\bvs\b|vj|selector|promoter|主理人|厂牌|成员)", re.I)
PUBLIC_FALLBACK_SOURCE_REF_RE = re.compile(r"^(source_ref:|src:|activity_src:)")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_hash(value: Any, length: int = 24) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:length]


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
    return s185.read_jsonl(path)


def compact_text(value: Any, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def compact_token(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(ch for ch in normalized if unicodedata.category(ch)[0] in {"L", "N"})


def row_group_id(row: dict[str, Any]) -> str:
    return str((row.get("source_group_row") or {}).get("group_id") or row.get("group_id") or "")


def source_group(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("source_group_row")
    return value if isinstance(value, dict) else {}


def display_text(row: dict[str, Any]) -> str:
    group = source_group(row)
    values = [
        row_group_id(row),
        *(row.get("display_names") or []),
        *(group.get("display_names") or []),
        group.get("identity_token") or "",
        *(row.get("unicode_compact_values") or []),
    ]
    return " ".join(compact_text(value, 160) for value in values if str(value or "").strip())


def collect_source_ref_ids(row: dict[str, Any]) -> list[str]:
    refs: set[str] = set()
    common = row.get("common_evidence") or {}
    for value in common.get("common_source_ref_ids") or []:
        if value:
            refs.add(str(value))
    for context in row.get("per_dj_context") or []:
        for value in context.get("source_ref_ids") or []:
            if value:
                refs.add(str(value))
        for event in context.get("event_sample") or []:
            value = event.get("source_ref_id")
            if value:
                refs.add(str(value))
    return sorted(refs)


def collect_source_ref_ids_by_dj(row: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, set[str]] = {}
    for context in row.get("per_dj_context") or []:
        profile = context.get("profile") or {}
        dj_id = str(profile.get("dj_id") or "")
        if not dj_id:
            continue
        bucket = result.setdefault(dj_id, set())
        for value in context.get("source_ref_ids") or []:
            if value:
                bucket.add(str(value))
        for event in context.get("event_sample") or []:
            value = event.get("source_ref_id")
            if value:
                bucket.add(str(value))
    return {key: sorted(values) for key, values in sorted(result.items())}


def archive_path_allowed(path: Path, allowed_root: Path) -> bool:
    try:
        path.resolve().relative_to(allowed_root.resolve())
        return True
    except (OSError, ValueError):
        return False


def connect_source_url_ro(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def source_url_rows_by_ref(
    source_url_db: Path,
    source_ref_ids: set[str],
    *,
    allowed_archive_root: Path,
) -> dict[str, dict[str, Any]]:
    if not source_ref_ids:
        return {}
    conn = connect_source_url_ro(source_url_db)
    if conn is None:
        return {}
    rows: dict[str, dict[str, Any]] = {}
    try:
        for source_ref_id in sorted(source_ref_ids):
            row = conn.execute(
                """
                SELECT source_ref_id, article_uid, article_id, source_account, title, post_date,
                       archive_raw_html_path, match_basis, confidence, entity_count, event_count,
                       local_image_count
                FROM article_source_url
                WHERE source_ref_id = ?
                LIMIT 1
                """,
                (source_ref_id,),
            ).fetchone()
            if not row:
                continue
            raw_path = str(row["archive_raw_html_path"] or "")
            archive_present = bool(raw_path)
            exact_file_exists = False
            allowed = False
            if archive_present:
                archive_path = Path(raw_path)
                allowed = archive_path_allowed(archive_path, allowed_archive_root)
                exact_file_exists = allowed and archive_path.is_file()
            rows[source_ref_id] = {
                "source_ref_id": source_ref_id,
                "article_uid": compact_text(row["article_uid"], 300),
                "article_id_hash": stable_hash(row["article_id"] or source_ref_id),
                "source_account": compact_text(row["source_account"], 240),
                "title": compact_text(row["title"], 500),
                "post_date": compact_text(row["post_date"], 80),
                "match_basis": compact_text(row["match_basis"], 160),
                "confidence": row["confidence"],
                "entity_count": row["entity_count"],
                "event_count": row["event_count"],
                "local_image_count": row["local_image_count"],
                "archive_raw_html_path_present": archive_present,
                "archive_path_allowed": allowed,
                "archive_exact_file_exists": exact_file_exists,
                "archive_path_sha256": hashlib.sha256(raw_path.encode("utf-8", errors="ignore")).hexdigest()
                if raw_path
                else "",
                "raw_source_url_emitted": False,
                "raw_archive_path_emitted": False,
            }
    finally:
        conn.close()
    return rows


def archive_coverage(row: dict[str, Any], source_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    by_dj = collect_source_ref_ids_by_dj(row)
    per_dj: dict[str, dict[str, Any]] = {}
    archive_refs: set[str] = set()
    row_refs = {ref for refs in by_dj.values() for ref in refs}
    for dj_id, refs in by_dj.items():
        hit_refs = [
            ref
            for ref in refs
            if source_rows.get(ref, {}).get("archive_raw_html_path_present")
            and source_rows.get(ref, {}).get("archive_path_allowed")
            and source_rows.get(ref, {}).get("archive_exact_file_exists")
        ]
        partial_refs = [ref for ref in refs if source_rows.get(ref, {}).get("archive_raw_html_path_present")]
        archive_refs.update(hit_refs)
        per_dj[dj_id] = {
            "source_ref_count": len(refs),
            "archive_hit_count": len(hit_refs),
            "archive_source_ref_ids": hit_refs[:12],
            "partial_archive_source_ref_ids": partial_refs[:12],
            "has_exact_archive": bool(hit_refs),
        }
    all_profile_count = len(by_dj)
    profiles_with_exact_archive = sum(1 for item in per_dj.values() if item["has_exact_archive"])
    any_archive = any(source_rows.get(ref, {}).get("archive_raw_html_path_present") for ref in row_refs)
    return {
        "profile_count": all_profile_count,
        "profiles_with_exact_archive": profiles_with_exact_archive,
        "full_exact_archive_coverage": all_profile_count > 0 and profiles_with_exact_archive == all_profile_count,
        "partial_archive_coverage": profiles_with_exact_archive > 0 and profiles_with_exact_archive < all_profile_count,
        "any_archive_row": any_archive,
        "archive_ready_source_ref_ids": sorted(archive_refs),
        "per_dj": per_dj,
    }


def source_seed_summary(row: dict[str, Any]) -> dict[str, Any]:
    common = row.get("common_evidence") or {}
    common_accounts = sorted({str(v) for v in common.get("common_source_accounts") or [] if str(v).strip()})
    common_titles = sorted(
        {
            str(v)
            for v in [
                *(common.get("common_source_titles") or []),
                *(common.get("common_event_titles") or []),
            ]
            if str(v).strip()
        }
    )
    common_venues = sorted(
        {
            str(v)
            for v in [
                *(common.get("common_venue_ids") or []),
                *(common.get("common_venue_names") or []),
            ]
            if str(v).strip()
        }
    )
    title_seed = s190.every_profile_has_title_seed(row)
    date_seed = s190.every_profile_has_date_seed(row)
    return {
        "common_source_accounts": common_accounts,
        "common_titles": common_titles,
        "common_venues": common_venues,
        "every_profile_has_title_seed": title_seed,
        "every_profile_has_date_seed": date_seed,
        "has_source_account_or_title_seed": bool(common_accounts or common_titles or title_seed),
        "has_provider_anchor": bool(common_venues),
    }


def provider_blockers(row: dict[str, Any]) -> list[str]:
    group = source_group(row)
    token_values = row.get("unicode_compact_values") or []
    token = str(token_values[0] if len(token_values) == 1 else group.get("identity_token") or "")
    reasons = set(group.get("s159_rejection_reasons") or [])
    common = row.get("common_evidence") or {}
    text = display_text(row)
    blockers: list[str] = []
    if not reasons <= s198.ALLOWED_REASONS:
        blockers.append("non_plain_ascii_cluster_rejection_reason")
    if any(ord(char) > 127 for char in token):
        blockers.append("non_ascii_compact_token_not_allowed_in_s198")
    if any(char.isdigit() for char in token):
        blockers.append("digit_token_not_allowed_in_s198")
    if ROLE_OR_COMPOUND_RE.search(text):
        blockers.append("role_or_compound_marker")
    if AKA_RE.search(text):
        blockers.append("aka_marker_requires_identity_disposition")
    if not common.get("common_source_ref_ids"):
        blockers.append("common_source_ref_missing")
    if not (common.get("common_source_titles") or common.get("common_event_titles")):
        blockers.append("common_source_or_event_title_missing")
    if len(common.get("common_source_accounts") or []) != 1:
        blockers.append("common_source_account_not_singleton")
    if not (common.get("common_venue_ids") or common.get("common_venue_names")):
        blockers.append("same_venue_or_provider_anchor_missing")
    if len(token) < 5:
        blockers.append("compact_token_too_short_without_strong_event_or_multivenue_anchor")
    return sorted(set(blockers))


def classify_provider_row(row: dict[str, Any]) -> dict[str, Any]:
    group = source_group(row)
    token_values = row.get("unicode_compact_values") or []
    token = str(token_values[0] if len(token_values) == 1 else group.get("identity_token") or "")
    text = display_text(row)
    blockers = provider_blockers(row)
    route = "S200_provider_residual_manual_or_acquisition"
    if "common_source_account_not_singleton" in blockers or "role_or_compound_marker" in blockers or "aka_marker_requires_identity_disposition" in blockers:
        route = "S200_provider_residual_conflict_or_risk_review"
    elif any(char.isdigit() for char in token):
        route = "S200B_digit_stage_name_exact_gate"
    elif DJ_PREFIX_RE.search(text):
        route = "S200C_dj_prefix_quote_normalization_gate"
    elif any(ord(char) > 127 for char in text):
        route = "S200D_unicode_bilingual_alias_gate"
    elif len(token) < 5:
        route = "S200A_short_token_evidence_gate"
    return {
        "schema_version": SCHEMA_VERSION + ".provider",
        "current_story_id": CURRENT_STORY_ID,
        "task_id": f"s200:provider:{stable_hash(row_group_id(row) + ''.join(row.get('dj_ids') or []), 16)}",
        "group_id": row_group_id(row),
        "dj_ids": row.get("dj_ids") or [],
        "display_names": row.get("display_names") or [],
        "unicode_compact_values": row.get("unicode_compact_values") or [],
        "s183_lane": row.get("s183_lane"),
        "s185_route": row.get("s185_route"),
        "route": route,
        "blockers": blockers,
        "next_gate": route,
        "can_enter_db3_write_now": False,
        "write_gate_requirements": [
            "common_source_ref_or_same_article_body_coverage",
            "same_source_title_or_same_event_title_or_exact_bio_profile",
            "all_profiles_display_or_alias_coverage",
            "single_writer_lock",
            "db3_backup",
            "BEGIN_IMMEDIATE_transaction",
            "postwrite_readback",
            "no_empty_overwrite",
        ],
        "common_evidence": row.get("common_evidence") or {},
    }


def classify_manual_row(row: dict[str, Any]) -> dict[str, Any]:
    group = source_group(row)
    text = display_text(row)
    risk = list(group.get("s183_risk_reasons") or row.get("s183_risk_reasons") or [])
    reasons = list(group.get("s159_rejection_reasons") or [])
    route = "S200_manual_identity_review"
    if "collaboration_marker" in risk or "separator_or_collaboration_marker_present" in reasons:
        route = "S200_manual_collaboration_alias_vs_compound_review"
    if AKA_RE.search(text):
        route = "S200_manual_aka_person_alias_source_anchor"
    if "risk_word_present" in reasons:
        route = "S200_manual_risk_word_disposition_review"
    if any(marker in risk for marker in ("lineup_or_count_marker", "collective_label_or_band_marker", "bio_sentence_or_role_marker")):
        route = "S200_manual_non_person_disposition_review"
    return {
        "schema_version": SCHEMA_VERSION + ".manual",
        "current_story_id": CURRENT_STORY_ID,
        "task_id": f"s200:manual:{stable_hash(row_group_id(row) + ''.join(row.get('dj_ids') or []), 16)}",
        "group_id": row_group_id(row),
        "dj_ids": row.get("dj_ids") or [],
        "display_names": row.get("display_names") or [],
        "unicode_compact_values": row.get("unicode_compact_values") or [],
        "s183_lane": row.get("s183_lane"),
        "s185_route": row.get("s185_route"),
        "route": route,
        "s183_risk_reasons": risk,
        "s159_rejection_reasons": reasons,
        "can_enter_db3_write_now": False,
        "next_gate": route,
        "required_disposition_answers": [
            "same_person_alias",
            "different_people_same_normalized_name",
            "collective_or_lineup_not_dj",
            "label_or_crew_or_promoter_not_dj",
            "bio_or_role_phrase_not_identity",
        ],
    }


def classify_external_row(row: dict[str, Any], source_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    coverage = archive_coverage(row, source_rows)
    seed = source_seed_summary(row)
    group = source_group(row)
    text = display_text(row)
    risk_reasons = list(group.get("s159_rejection_reasons") or [])
    needs_manual_identity = bool(
        "risk_word_present" in risk_reasons
        or AKA_RE.search(text)
        or ("group_size_not_two" in risk_reasons and "aka" in compact_token(text))
    )
    all_refs = collect_source_ref_ids(row)
    route = "P4_pure_manual_seed"
    if needs_manual_identity:
        route = "P4_manual_identity_risk_review"
    elif coverage["full_exact_archive_coverage"]:
        route = "P0_archive_mptext_replay_full_coverage"
    elif coverage["partial_archive_coverage"] or coverage["any_archive_row"]:
        route = "P1_source_provider_recover_missing_archive"
    elif seed["has_source_account_or_title_seed"] or seed["has_provider_anchor"]:
        route = "P2_source_provider_acquisition"
    elif any(PUBLIC_FALLBACK_SOURCE_REF_RE.search(ref) for ref in all_refs):
        route = "P3_public_no_cookie_crawl_canary"
    return {
        "schema_version": SCHEMA_VERSION + ".external",
        "current_story_id": CURRENT_STORY_ID,
        "task_id": f"s200:external:{route}:{stable_hash(row_group_id(row) + ''.join(row.get('dj_ids') or []), 16)}",
        "group_id": row_group_id(row),
        "dj_ids": row.get("dj_ids") or [],
        "display_names": row.get("display_names") or [],
        "unicode_compact_values": row.get("unicode_compact_values") or [],
        "s183_lane": row.get("s183_lane"),
        "s185_route": row.get("s185_route"),
        "route": route,
        "next_gate": route,
        "source_ref_ids": all_refs[:40],
        "source_ref_ids_by_dj": collect_source_ref_ids_by_dj(row),
        "archive_coverage": coverage,
        "source_seed": seed,
        "manual_identity_review_required": needs_manual_identity,
        "s159_rejection_reasons": risk_reasons,
        "can_enter_db3_write_now": False,
        "write_authorization": {
            "db1_mutation": False,
            "db2_mutation": False,
            "db3_mutation": False,
            "db2_projection": False,
            "deploy_upload_review_release": False,
        },
    }


def s201_archive_replay_row(row: dict[str, Any], source_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ready_refs = row["archive_coverage"]["archive_ready_source_ref_ids"]
    return {
        "schema_version": SCHEMA_VERSION + ".s201_archive_replay_queue",
        "current_story_id": CURRENT_STORY_ID,
        "task_id": f"s201:archive-replay:{stable_hash(row['group_id'] + ''.join(row.get('dj_ids') or []), 16)}",
        "group_id": row["group_id"],
        "dj_ids": row.get("dj_ids") or [],
        "display_names": row.get("display_names") or [],
        "route": "S201_exact_local_archive_replay",
        "source_ref_ids": ready_refs,
        "source_ref_ids_by_dj": row["source_ref_ids_by_dj"],
        "article_uid_by_source_ref": {
            ref: source_rows[ref]["article_uid"]
            for ref in ready_refs
            if source_rows.get(ref, {}).get("article_uid")
        },
        "raw_source_url_emitted": False,
        "raw_archive_path_emitted": False,
        "db3_write_allowed_now": False,
    }


def collect_all_source_rows(
    *,
    rows: list[dict[str, Any]],
    source_url_db: Path,
    allowed_archive_root: Path,
) -> dict[str, dict[str, Any]]:
    refs: set[str] = set()
    for row in rows:
        refs.update(collect_source_ref_ids(row))
    return source_url_rows_by_ref(source_url_db, refs, allowed_archive_root=allowed_archive_root)


def scan_outputs_for_safety(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if not path.exists() or path.is_dir():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if RAW_URL_RE.search(text):
            findings.append(f"raw_url_emitted:{rel_path(path)}")
        if RAW_ARCHIVE_PATH_RE.search(text):
            findings.append(f"raw_path_emitted:{rel_path(path)}")
        if SECRET_LIKE_RE.search(text):
            findings.append(f"secret_like_text_emitted:{rel_path(path)}")
    return findings


def build_superbatch(
    *,
    s199_dir: Path,
    source_url_db: Path,
    out_dir: Path,
    scorecard_path: Path,
    allowed_archive_root: Path,
) -> dict[str, Any]:
    generated_at = now_iso()
    out_dir.mkdir(parents=True, exist_ok=True)
    provider_input = s199_dir / "provider_crosscheck_rows_s185.jsonl"
    manual_input = s199_dir / "manual_review_rows_s185.jsonl"
    external_input = s199_dir / "external_or_manual_acquisition_rows_s185.jsonl"

    provider_rows = read_jsonl(provider_input)
    manual_rows = read_jsonl(manual_input)
    external_rows = read_jsonl(external_input)
    source_rows = collect_all_source_rows(
        rows=external_rows,
        source_url_db=source_url_db,
        allowed_archive_root=allowed_archive_root,
    )

    provider = [classify_provider_row(row) for row in provider_rows]
    manual = [classify_manual_row(row) for row in manual_rows]
    external = [classify_external_row(row, source_rows) for row in external_rows]

    p0 = [row for row in external if row["route"] == "P0_archive_mptext_replay_full_coverage"]
    p1 = [row for row in external if row["route"] == "P1_source_provider_recover_missing_archive"]
    p2 = [row for row in external if row["route"] == "P2_source_provider_acquisition"]
    p3 = [row for row in external if row["route"] == "P3_public_no_cookie_crawl_canary"]
    manual_risk = [row for row in external if row["route"] == "P4_manual_identity_risk_review"]
    s201_queue = [s201_archive_replay_row(row, source_rows) for row in p0]

    tasks = [
        *[
            {
                "task_id": row["task_id"],
                "lane": "provider_residual",
                "route": row["route"],
                "group_id": row["group_id"],
                "next_gate": row["next_gate"],
            }
            for row in provider
        ],
        *[
            {
                "task_id": row["task_id"],
                "lane": "manual_review",
                "route": row["route"],
                "group_id": row["group_id"],
                "next_gate": row["next_gate"],
            }
            for row in manual
        ],
        *[
            {
                "task_id": row["task_id"],
                "lane": "external_or_manual_acquisition",
                "route": row["route"],
                "group_id": row["group_id"],
                "next_gate": row["next_gate"],
            }
            for row in external
        ],
    ]

    artifacts = {
        "report_json": rel_path(out_dir / f"{REPORT_STEM}.json"),
        "scorecard": rel_path(scorecard_path),
        "provider_residual_jsonl": rel_path(out_dir / "s200_provider_residual_rows.jsonl"),
        "manual_review_jsonl": rel_path(out_dir / "s200_manual_disposition_review_rows.jsonl"),
        "external_superqueue_jsonl": rel_path(out_dir / "s200_external_acquisition_superqueue.jsonl"),
        "p0_archive_replay_jsonl": rel_path(out_dir / "s200_p0_archive_replay_full_coverage.jsonl"),
        "p1_recover_missing_archive_jsonl": rel_path(out_dir / "s200_p1_source_provider_recover_missing_archive.jsonl"),
        "p2_source_provider_acquisition_jsonl": rel_path(out_dir / "s200_p2_source_provider_acquisition.jsonl"),
        "p3_public_no_cookie_canary_jsonl": rel_path(out_dir / "s200_p3_public_no_cookie_crawl_canary.jsonl"),
        "manual_identity_risk_jsonl": rel_path(out_dir / "s200_manual_identity_risk_review.jsonl"),
        "s201_archive_replay_queue_jsonl": rel_path(out_dir / "s201_exact_local_archive_replay_queue.jsonl"),
        "tasks_jsonl": rel_path(out_dir / "s200_tasks.jsonl"),
    }

    write_jsonl(out_dir / "s200_provider_residual_rows.jsonl", provider)
    write_jsonl(out_dir / "s200_manual_disposition_review_rows.jsonl", manual)
    write_jsonl(out_dir / "s200_external_acquisition_superqueue.jsonl", external)
    write_jsonl(out_dir / "s200_p0_archive_replay_full_coverage.jsonl", p0)
    write_jsonl(out_dir / "s200_p1_source_provider_recover_missing_archive.jsonl", p1)
    write_jsonl(out_dir / "s200_p2_source_provider_acquisition.jsonl", p2)
    write_jsonl(out_dir / "s200_p3_public_no_cookie_crawl_canary.jsonl", p3)
    write_jsonl(out_dir / "s200_manual_identity_risk_review.jsonl", manual_risk)
    write_jsonl(out_dir / "s201_exact_local_archive_replay_queue.jsonl", s201_queue)
    write_jsonl(out_dir / "s200_tasks.jsonl", tasks)

    safety_scan_paths = [out_dir / Path(value).name for key, value in artifacts.items() if key.endswith("jsonl")]
    safety_findings = scan_outputs_for_safety(safety_scan_paths)
    decision = (
        "atlas_relation_identity_residual_repair_superbatch_s200_ready_for_s201_archive_replay"
        if s201_queue and not safety_findings
        else "atlas_relation_identity_residual_repair_superbatch_s200_ready_report_only"
        if not safety_findings
        else "atlas_relation_identity_residual_repair_superbatch_s200_failed_safety_scan"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "current_story_id": CURRENT_STORY_ID,
        "generated_at": generated_at,
        "decision": decision,
        "inputs": {
            "s199_dir": rel_path(s199_dir),
            "provider_input": rel_path(provider_input),
            "manual_input": rel_path(manual_input),
            "external_input": rel_path(external_input),
            "source_url_db": rel_path(source_url_db),
            "allowed_archive_root_sha256": hashlib.sha256(str(allowed_archive_root).encode("utf-8")).hexdigest(),
        },
        "counts": {
            "input_group_count": len(provider_rows) + len(manual_rows) + len(external_rows),
            "provider_residual_count": len(provider_rows),
            "manual_review_count": len(manual_rows),
            "external_or_manual_count": len(external_rows),
            "provider_route_counts": dict(sorted(Counter(row["route"] for row in provider).items())),
            "manual_route_counts": dict(sorted(Counter(row["route"] for row in manual).items())),
            "external_route_counts": dict(sorted(Counter(row["route"] for row in external).items())),
            "s201_archive_replay_queue_count": len(s201_queue),
            "source_url_rows_matched": len(source_rows),
            "archive_exact_file_source_ref_count": sum(1 for row in source_rows.values() if row["archive_exact_file_exists"]),
            "can_enter_db3_write_now": 0,
        },
        "samples": {
            "provider": provider[:8],
            "manual": manual[:8],
            "external_p0": p0[:8],
            "external_p1": p1[:8],
            "external_p2": p2[:8],
            "external_p3": p3[:8],
            "manual_identity_risk": manual_risk[:8],
        },
        "execution_cursor": {
            "next_story_id": "S201",
            "next_input": artifacts["s201_archive_replay_queue_jsonl"],
            "next_action": "Run exact local archive replay over P0 rows, then feed article-ready artifacts into S193/S194 DB3 write gates under lock/backup/readback.",
            "db3_write_allowed_now": False,
            "db2_projection_allowed_now": False,
            "deploy_upload_review_release_allowed_now": False,
        },
        "weapon_plan": s190.weapon_plan(),
        "safety": {
            "report_only": True,
            "network_fetch": False,
            "db1_mutation": False,
            "db2_mutation": False,
            "db3_mutation": False,
            "db2_projection": False,
            "deploy_upload_review_release": False,
            "cookie_token_secret_read": False,
            "secret_values_printed": False,
            "raw_source_url_emitted": False,
            "raw_archive_path_emitted": False,
            "safety_findings": safety_findings,
        },
        "artifacts": artifacts,
    }
    atomic_write_json(out_dir / f"{REPORT_STEM}.json", report)
    write_scorecard(scorecard_path, report)
    return report


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    counts = report["counts"]
    lines = [
        "# Weekly Atlas Relation Identity Residual Repair Superbatch S200",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Input groups: `{counts['input_group_count']}`",
        f"- Provider residual: `{counts['provider_residual_count']}`",
        f"- Manual review: `{counts['manual_review_count']}`",
        f"- External/manual acquisition: `{counts['external_or_manual_count']}`",
        f"- S201 archive replay queue: `{counts['s201_archive_replay_queue_count']}`",
        f"- DB3 write-ready now: `{counts['can_enter_db3_write_now']}`",
        "",
        "## External Routes",
        "",
    ]
    for key, value in (counts.get("external_route_counts") or {}).items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Provider Routes", ""])
    for key, value in (counts.get("provider_route_counts") or {}).items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Manual Routes", ""])
    for key, value in (counts.get("manual_route_counts") or {}).items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Report-only queue compiler. No network fetch, no DB1/DB2/DB3 write, no DB2 projection, no deploy/upload/review/release.",
            "- Raw source URLs and exact archive paths are not emitted; archive paths are represented only by hashes and exact-file booleans.",
            "- P0 is the next execution lane: exact local archive replay, then S193/S194 guarded DB3 write gates only if article evidence passes.",
            "",
            "## Artifacts",
        ]
    )
    for key, value in report["artifacts"].items():
        lines.append(f"- `{key}`: `{value}`")
    if report["safety"]["safety_findings"]:
        lines.extend(["", "## Safety Findings", ""])
        for item in report["safety"]["safety_findings"]:
            lines.append(f"- `{item}`")
    atomic_write_text(path, "\n".join(lines) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s199-dir", type=Path, default=DEFAULT_S199_DIR)
    parser.add_argument("--source-url-db", type=Path, default=DEFAULT_SOURCE_URL_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--allowed-archive-root", type=Path, default=DEFAULT_ALLOWED_ARCHIVE_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_superbatch(
        s199_dir=args.s199_dir,
        source_url_db=args.source_url_db,
        out_dir=args.out_dir,
        scorecard_path=args.scorecard,
        allowed_archive_root=args.allowed_archive_root,
    )
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "counts": report["counts"],
                "out_dir": rel_path(args.out_dir),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if not report["safety"]["safety_findings"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
