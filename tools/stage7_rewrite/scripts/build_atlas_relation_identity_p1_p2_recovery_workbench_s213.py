#!/usr/bin/env python3
"""Build S213 recovery workbench for S212 P1/P2/provider/manual residuals.

S213 is a no-write bridge after S212. It turns the remaining P1/P2 source
recovery rows into S191/S201-compatible queues, and keeps provider/manual rows
as explicit evidence tasks. It never emits raw source URLs or archive paths.
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
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_source_anchor_batch_s167 as s167


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S213"
REPORT_STEM = "atlas_relation_identity_p1_p2_recovery_workbench_s213"
SCHEMA_VERSION = f"{REPORT_STEM}.v1"

DEFAULT_S212_DIR = REPORTS_ROOT / "atlas_relation_identity_residual_repair_superbatch_s212_after_s209_20260602"
DEFAULT_ATLAS_DB = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_SOURCE_URL_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_source_url_recovery_139123_candidate"
    / "atlas_source_url_recovery.sqlite"
)
DEFAULT_ALLOWED_ARCHIVE_ROOT = Path(r"D:\downstream_results\stage7_rewrite\longrun\WHERE_TO_RAVE_WECHAT_SYNC_20260508")
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_p1_p2_recovery_workbench_s213_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_P1_P2_RECOVERY_WORKBENCH_S213_20260602.md"

RAW_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
RAW_PATH_RE = re.compile(r"(?i)(?:\b[A-Z]:\\[^\"'\n\r]+|/mnt/[a-z](?:/[^\"'\n\r]*)?)")
SECRET_RE = re.compile(r"(?i)(cookie|authorization|x-auth-key|api[_-]?key|secret|bearer\s+[a-z0-9._-]{8,})")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel_path(path: Path) -> str:
    return s167.rel_path(path)


def stable_hash(value: Any, length: int = 24) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:length]


def compact(value: Any, limit: int = 800) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def scrub_text(value: Any, limit: int = 800) -> str:
    text = compact(value, limit)
    text = RAW_URL_RE.sub("redacted-url", text)
    text = RAW_PATH_RE.sub("redacted-local-path", text)
    text = SECRET_RE.sub("redacted-secret-word", text)
    return text


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: expected JSON object")
            rows.append(value)
    return rows


def connect_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def archive_allowed(path: Path, allowed_root: Path) -> bool:
    try:
        path.resolve().relative_to(allowed_root.resolve())
        return True
    except (OSError, ValueError):
        return False


def source_ref_meta(atlas_conn: sqlite3.Connection, source_ref_id: str) -> dict[str, Any] | None:
    return row_dict(
        atlas_conn.execute(
            """
            SELECT source_ref_id, source_account, source_title, post_date, source_kind
            FROM source_ref
            WHERE source_ref_id = ?
            LIMIT 1
            """,
            (source_ref_id,),
        ).fetchone()
    )


def source_url_direct(source_conn: sqlite3.Connection, source_ref_id: str) -> dict[str, Any] | None:
    return row_dict(source_conn.execute("SELECT * FROM article_source_url WHERE source_ref_id = ? LIMIT 1", (source_ref_id,)).fetchone())


def source_url_fallback(source_conn: sqlite3.Connection, meta: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str, int]:
    if not meta:
        return None, "source_ref_missing_in_db3", 0
    account = compact(meta.get("source_account"), 240)
    title = compact(meta.get("source_title"), 500)
    post_date = compact(meta.get("post_date"), 80)
    if not account or not title:
        return None, "missing_account_or_title", 0
    if post_date:
        rows = [
            row_dict(row)
            for row in source_conn.execute(
                """
                SELECT * FROM article_source_url
                WHERE source_account = ? AND title = ? AND post_date = ?
                ORDER BY confidence DESC, article_uid
                """,
                (account, title, post_date),
            ).fetchall()
        ]
        method = "account_title_post_date_unique"
    else:
        rows = [
            row_dict(row)
            for row in source_conn.execute(
                """
                SELECT * FROM article_source_url
                WHERE source_account = ? AND title = ?
                ORDER BY confidence DESC, article_uid
                """,
                (account, title),
            ).fetchall()
        ]
        method = "account_title_unique_without_post_date"
    rows = [row for row in rows if row]
    if len(rows) == 1:
        return rows[0], method, 1
    if not rows:
        return None, "no_account_title_match", 0
    return None, f"ambiguous_{method}", len(rows)


def resolve_ref(
    *,
    source_ref_id: str,
    atlas_conn: sqlite3.Connection,
    source_conn: sqlite3.Connection,
    allowed_archive_root: Path,
) -> dict[str, Any]:
    meta = source_ref_meta(atlas_conn, source_ref_id)
    article = source_url_direct(source_conn, source_ref_id)
    method = "direct_source_ref_id" if article else ""
    candidate_count = 1 if article else 0
    if not article:
        article, method, candidate_count = source_url_fallback(source_conn, meta)
    archive_raw = compact((article or {}).get("archive_raw_html_path"), 5000)
    archive_present = bool(archive_raw)
    archive_path_allowed = False
    archive_exact_file_exists = False
    if archive_raw:
        archive_path = Path(archive_raw)
        archive_path_allowed = archive_allowed(archive_path, allowed_archive_root)
        archive_exact_file_exists = archive_path_allowed and archive_path.is_file()
    source_url_present = bool(compact((article or {}).get("source_url"), 5000))
    return {
        "source_ref_id": source_ref_id,
        "db3_source_ref_present": bool(meta),
        "source_account": scrub_text((article or meta or {}).get("source_account"), 240),
        "title": scrub_text((article or {}).get("title") or (meta or {}).get("source_title"), 500),
        "post_date": scrub_text((article or meta or {}).get("post_date"), 80),
        "source_kind": scrub_text((meta or {}).get("source_kind"), 120),
        "source_url_resolved": bool(article and source_url_present),
        "resolution_method": method,
        "resolution_candidate_count": candidate_count,
        "resolved_article_source_ref_id": scrub_text((article or {}).get("source_ref_id"), 160),
        "article_uid_hash": stable_hash((article or {}).get("article_uid") or (article or {}).get("article_id") or source_ref_id),
        "archive_raw_html_path_present": archive_present,
        "archive_path_allowed": archive_path_allowed,
        "archive_exact_file_exists": archive_exact_file_exists,
        "archive_path_sha256": hashlib.sha256(archive_raw.encode("utf-8", errors="ignore")).hexdigest() if archive_raw else "",
        "raw_source_url_emitted": False,
        "raw_archive_path_emitted": False,
    }


def per_dj_resolution(
    row: dict[str, Any],
    *,
    atlas_conn: sqlite3.Connection,
    source_conn: sqlite3.Connection,
    allowed_archive_root: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    resolved_by_ref: dict[str, dict[str, Any]] = {}
    per_dj: dict[str, dict[str, Any]] = {}
    for dj_id, refs in (row.get("source_ref_ids_by_dj") or {}).items():
        ref_rows = []
        for ref in refs:
            ref_id = compact(ref, 160)
            if not ref_id:
                continue
            resolved = resolved_by_ref.get(ref_id)
            if resolved is None:
                resolved = resolve_ref(
                    source_ref_id=ref_id,
                    atlas_conn=atlas_conn,
                    source_conn=source_conn,
                    allowed_archive_root=allowed_archive_root,
                )
                resolved_by_ref[ref_id] = resolved
            ref_rows.append(resolved)
        exact = [item for item in ref_rows if item["archive_exact_file_exists"]]
        fetch_ready = [item for item in ref_rows if item["source_url_resolved"] and not item["archive_exact_file_exists"]]
        per_dj[str(dj_id)] = {
            "source_ref_count": len(ref_rows),
            "source_url_resolved_count": sum(1 for item in ref_rows if item["source_url_resolved"]),
            "exact_archive_count": len(exact),
            "public_fetch_ready_count": len(fetch_ready),
            "has_exact_archive": bool(exact),
            "has_public_fetch_ready": bool(fetch_ready),
            "exact_archive_source_ref_ids": [item["source_ref_id"] for item in exact[:10]],
            "public_fetch_source_ref_ids": [item["source_ref_id"] for item in fetch_ready[:10]],
            "blocked_source_ref_count": sum(1 for item in ref_rows if not item["source_url_resolved"] and not item["archive_exact_file_exists"]),
        }
    return per_dj, list(resolved_by_ref.values())


def seed_event(ref: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_ref_id": ref["source_ref_id"],
        "source_account": ref.get("source_account", ""),
        "source_title": ref.get("title", ""),
        "event_title": ref.get("title", ""),
        "starts_at": "",
        "post_date": ref.get("post_date", ""),
        "venue_name": "",
        "city": "",
        "group_id": row.get("group_id", ""),
    }


def classify_source_row(row: dict[str, Any], per_dj: dict[str, dict[str, Any]], refs: list[dict[str, Any]]) -> dict[str, Any]:
    profile_count = len(per_dj)
    profiles_with_archive = sum(1 for item in per_dj.values() if item["has_exact_archive"])
    profiles_with_fetch = sum(1 for item in per_dj.values() if item["has_public_fetch_ready"])
    exact_refs = [ref for ref in refs if ref["archive_exact_file_exists"]]
    fetch_refs = [ref for ref in refs if ref["source_url_resolved"] and not ref["archive_exact_file_exists"]]
    source_seed = row.get("source_seed") or {}
    if profile_count > 0 and profiles_with_archive == profile_count:
        route = "S213A_exact_archive_replay_ready"
        next_gate = "S201_exact_archive_replay_then_S193_S194_write_gate"
    elif exact_refs and fetch_refs:
        route = "S213B_partial_archive_plus_public_fetch"
        next_gate = "S201_partial_replay_plus_S191_fetch_then_rebuild_archive_evidence_gate"
    elif profile_count > 0 and profiles_with_fetch == profile_count:
        route = "S213C_public_fetch_canary_ready"
        next_gate = "S191_bounded_public_fetch_canary"
    elif source_seed.get("has_source_account_or_title_seed") or source_seed.get("has_provider_anchor"):
        route = "S213D_db2_source_provider_acquisition_spool"
        next_gate = "db2ctl_profile_jsonl_spool_source_provider_acquisition"
    else:
        route = "S213E_manual_source_seed_required"
        next_gate = "manual_source_ref_or_provider_seed_required"
    return {
        "schema_version": SCHEMA_VERSION + ".source_row",
        "current_story_id": CURRENT_STORY_ID,
        "task_id": f"s213:source:{stable_hash(row.get('task_id') or row.get('group_id') or row.get('dj_ids'), 18)}",
        "group_id": row.get("group_id"),
        "dj_ids": row.get("dj_ids") or [],
        "display_names": row.get("display_names") or [],
        "unicode_compact_values": row.get("unicode_compact_values") or [],
        "input_route": row.get("route"),
        "route": route,
        "next_gate": next_gate,
        "per_dj_resolution": per_dj,
        "source_ref_count": len(refs),
        "source_url_resolved_ref_count": sum(1 for ref in refs if ref["source_url_resolved"]),
        "exact_archive_ref_count": len(exact_refs),
        "public_fetch_ready_ref_count": len(fetch_refs),
        "source_seed": source_seed,
        "can_enter_db3_write_now": False,
        "db3_write_allowed_now": False,
        "db2_projection_allowed_now": False,
        "raw_source_url_emitted": False,
        "raw_archive_path_emitted": False,
    }


def build_s201_queue(rows: list[dict[str, Any]], *, full_only: bool) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for row in rows:
        exact_refs = sorted(
            {
                ref
                for item in row["per_dj_resolution"].values()
                for ref in item.get("exact_archive_source_ref_ids") or []
            }
        )
        if not exact_refs:
            continue
        if full_only and row["route"] != "S213A_exact_archive_replay_ready":
            continue
        queue.append(
            {
                "schema_version": SCHEMA_VERSION + ".s201_queue",
                "current_story_id": CURRENT_STORY_ID,
                "task_id": f"s213:s201:{stable_hash(row['group_id'] + ''.join(row.get('dj_ids') or []), 18)}",
                "group_id": row["group_id"],
                "dj_ids": row.get("dj_ids") or [],
                "display_names": row.get("display_names") or [],
                "route": "S201_exact_local_archive_replay" if full_only else "S201_partial_local_archive_replay_report_only",
                "source_ref_ids": exact_refs,
                "db3_write_allowed_now": False,
            }
        )
    return queue


def build_s191_queue(rows: list[dict[str, Any]], ref_map: dict[str, dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    for row in rows:
        seed_events: list[dict[str, Any]] = []
        for item in row["per_dj_resolution"].values():
            for ref_id in item.get("public_fetch_source_ref_ids") or []:
                if ref_id in seen_refs:
                    continue
                ref = ref_map.get(ref_id)
                if not ref:
                    continue
                seed_events.append(seed_event(ref, row))
                seen_refs.add(ref_id)
                if 0 < limit <= len(seen_refs):
                    break
            if 0 < limit <= len(seen_refs):
                break
        if seed_events:
            queue.append(
                {
                    "schema_version": SCHEMA_VERSION + ".s191_queue",
                    "current_story_id": CURRENT_STORY_ID,
                    "task_id": f"s213:s191:{stable_hash(row['group_id'] + ''.join(row.get('dj_ids') or []), 18)}",
                    "group_id": row["group_id"],
                    "dj_ids": row.get("dj_ids") or [],
                    "display_names": row.get("display_names") or [],
                    "route": "S213_to_S191_bounded_public_fetch",
                    "seed_events": seed_events,
                    "db3_write_allowed_now": False,
                    "db2_projection_allowed_now": False,
                }
            )
        if 0 < limit <= len(seen_refs):
            break
    return queue


def provider_manual_task(row: dict[str, Any], lane: str) -> dict[str, Any]:
    route = row.get("route") or "unknown"
    if "non_person" in str(route):
        next_gate = "strict_disposition_row_gate_only_if_not_already_closed"
    elif "aka" in str(route).casefold():
        next_gate = "source_article_alias_coverage_required_before_identity_merge"
    elif "collaboration" in str(route).casefold() or "compound" in str(route).casefold():
        next_gate = "distinguish_collaboration_slash_pair_from_stage_alias"
    elif lane == "provider_residual":
        next_gate = "source_ref_or_same_article_body_coverage_required"
    else:
        next_gate = "manual_evidence_required"
    return {
        "schema_version": SCHEMA_VERSION + ".provider_manual_task",
        "current_story_id": CURRENT_STORY_ID,
        "task_id": f"s213:{lane}:{stable_hash(row.get('task_id') or row.get('group_id') or row.get('dj_ids'), 18)}",
        "lane": lane,
        "group_id": row.get("group_id"),
        "dj_ids": row.get("dj_ids") or [],
        "display_names": row.get("display_names") or [],
        "input_route": route,
        "blockers": row.get("blockers") or row.get("s183_risk_reasons") or row.get("s159_rejection_reasons") or [],
        "next_gate": next_gate,
        "exclude_if_label_collective_lineup_or_bio_phrase": True,
        "can_enter_db3_write_now": False,
        "db3_write_allowed_now": False,
        "db2_projection_allowed_now": False,
    }


def scan_public_outputs(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if RAW_URL_RE.search(text):
            findings.append(f"raw_url_emitted:{rel_path(path)}")
        if RAW_PATH_RE.search(text):
            findings.append(f"raw_path_emitted:{rel_path(path)}")
        if SECRET_RE.search(text):
            findings.append(f"secret_like_text_emitted:{rel_path(path)}")
    return findings


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    counts = report["counts"]
    lines = [
        "# Weekly Atlas Relation Identity P1/P2 Recovery Workbench S213",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Input groups: `{counts['input_group_count']}`",
        f"- P1 rows: `{counts['p1_input_count']}`",
        f"- P2 rows: `{counts['p2_input_count']}`",
        f"- Provider/manual task rows: `{counts['provider_manual_task_count']}`",
        f"- Source-ref rows inspected: `{counts['source_ref_count']}`",
        f"- Resolved source-url refs: `{counts['source_url_resolved_ref_count']}`",
        f"- Exact archive refs: `{counts['exact_archive_ref_count']}`",
        f"- S201 full replay queue: `{counts['s201_full_replay_queue_count']}`",
        f"- S201 partial replay queue: `{counts['s201_partial_replay_queue_count']}`",
        f"- S191 fetch canary groups/source refs: `{counts['s191_fetch_canary_group_count']}` / `{counts['s191_fetch_canary_source_ref_count']}`",
        "",
        "## Boundaries",
        "",
        "- Report-only workbench. No DB1/DB2/DB3 write, no DB2 projection, no deploy/upload/review/release.",
        "- Raw source URLs and archive paths are not emitted. URL fetch, if run later through S191, keeps raw URLs inside private sidecars only.",
        "- Provider/manual lanes remain blocked until source-ref/article evidence or strict disposition gates pass.",
        "",
        "## Route Counts",
    ]
    for key, value in sorted((counts.get("source_route_counts") or {}).items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Artifacts"])
    for key, value in report["artifacts"].items():
        lines.append(f"- `{key}`: `{value}`")
    atomic_write_text(path, "\n".join(lines) + "\n")


def build_workbench(
    *,
    s212_dir: Path,
    atlas_db: Path,
    source_url_db: Path,
    allowed_archive_root: Path,
    out_dir: Path,
    scorecard_path: Path,
    s191_limit: int,
) -> dict[str, Any]:
    generated_at = now_iso()
    out_dir.mkdir(parents=True, exist_ok=True)
    p1_rows = read_jsonl(s212_dir / "s200_p1_source_provider_recover_missing_archive.jsonl")
    p2_rows = read_jsonl(s212_dir / "s200_p2_source_provider_acquisition.jsonl")
    provider_rows = read_jsonl(s212_dir / "s200_provider_residual_rows.jsonl")
    manual_rows = read_jsonl(s212_dir / "s200_manual_disposition_review_rows.jsonl")
    manual_risk_rows = read_jsonl(s212_dir / "s200_manual_identity_risk_review.jsonl")

    ref_map: dict[str, dict[str, Any]] = {}
    source_workbench: list[dict[str, Any]] = []
    atlas_conn = connect_ro(atlas_db)
    source_conn = connect_ro(source_url_db)
    try:
        for row in [*p1_rows, *p2_rows]:
            per_dj, refs = per_dj_resolution(
                row,
                atlas_conn=atlas_conn,
                source_conn=source_conn,
                allowed_archive_root=allowed_archive_root,
            )
            for ref in refs:
                ref_map[ref["source_ref_id"]] = ref
            source_workbench.append(classify_source_row(row, per_dj, refs))
    finally:
        atlas_conn.close()
        source_conn.close()

    provider_manual_tasks = [
        *[provider_manual_task(row, "provider_residual") for row in provider_rows],
        *[provider_manual_task(row, "manual_review") for row in manual_rows],
        *[provider_manual_task(row, "manual_identity_risk") for row in manual_risk_rows],
    ]
    s201_full = build_s201_queue(source_workbench, full_only=True)
    s201_partial = build_s201_queue(source_workbench, full_only=False)
    s191_queue = build_s191_queue(source_workbench, ref_map, limit=s191_limit)
    db2_spool = [row for row in source_workbench if row["route"] == "S213D_db2_source_provider_acquisition_spool"]
    blocked = [row for row in source_workbench if row["route"] == "S213E_manual_source_seed_required"]

    artifacts = {
        "report_json": rel_path(out_dir / f"{REPORT_STEM}.json"),
        "scorecard": rel_path(scorecard_path),
        "source_workbench_jsonl": rel_path(out_dir / "s213_source_recovery_workbench.jsonl"),
        "s201_full_archive_replay_queue_jsonl": rel_path(out_dir / "s213_s201_full_archive_replay_queue.jsonl"),
        "s201_partial_archive_replay_queue_jsonl": rel_path(out_dir / "s213_s201_partial_archive_replay_queue.jsonl"),
        "s191_fetch_canary_queue_jsonl": rel_path(out_dir / "s213_s191_fetch_canary_queue.jsonl"),
        "db2_source_provider_spool_jsonl": rel_path(out_dir / "s213_db2_source_provider_spool_queue.jsonl"),
        "provider_manual_tasks_jsonl": rel_path(out_dir / "s213_provider_manual_evidence_tasks.jsonl"),
        "blocked_source_seed_rows_jsonl": rel_path(out_dir / "s213_blocked_source_seed_rows.jsonl"),
    }
    write_jsonl(out_dir / "s213_source_recovery_workbench.jsonl", source_workbench)
    write_jsonl(out_dir / "s213_s201_full_archive_replay_queue.jsonl", s201_full)
    write_jsonl(out_dir / "s213_s201_partial_archive_replay_queue.jsonl", s201_partial)
    write_jsonl(out_dir / "s213_s191_fetch_canary_queue.jsonl", s191_queue)
    write_jsonl(out_dir / "s213_db2_source_provider_spool_queue.jsonl", db2_spool)
    write_jsonl(out_dir / "s213_provider_manual_evidence_tasks.jsonl", provider_manual_tasks)
    write_jsonl(out_dir / "s213_blocked_source_seed_rows.jsonl", blocked)

    s191_ref_count = sum(len(row.get("seed_events") or []) for row in s191_queue)
    counts = {
        "input_group_count": len(p1_rows) + len(p2_rows) + len(provider_rows) + len(manual_rows) + len(manual_risk_rows),
        "p1_input_count": len(p1_rows),
        "p2_input_count": len(p2_rows),
        "provider_manual_task_count": len(provider_manual_tasks),
        "source_ref_count": len(ref_map),
        "source_url_resolved_ref_count": sum(1 for ref in ref_map.values() if ref["source_url_resolved"]),
        "exact_archive_ref_count": sum(1 for ref in ref_map.values() if ref["archive_exact_file_exists"]),
        "source_route_counts": dict(sorted(Counter(row["route"] for row in source_workbench).items())),
        "s201_full_replay_queue_count": len(s201_full),
        "s201_partial_replay_queue_count": len(s201_partial),
        "s191_fetch_canary_group_count": len(s191_queue),
        "s191_fetch_canary_source_ref_count": s191_ref_count,
        "db2_source_provider_spool_count": len(db2_spool),
        "blocked_source_seed_row_count": len(blocked),
    }
    output_paths = [
        out_dir / "s213_source_recovery_workbench.jsonl",
        out_dir / "s213_s201_full_archive_replay_queue.jsonl",
        out_dir / "s213_s201_partial_archive_replay_queue.jsonl",
        out_dir / "s213_s191_fetch_canary_queue.jsonl",
        out_dir / "s213_db2_source_provider_spool_queue.jsonl",
        out_dir / "s213_provider_manual_evidence_tasks.jsonl",
        out_dir / "s213_blocked_source_seed_rows.jsonl",
    ]
    safety_findings = scan_public_outputs(output_paths)
    decision = (
        "atlas_relation_identity_p1_p2_recovery_workbench_s213_failed_safety_scan"
        if safety_findings
        else "atlas_relation_identity_p1_p2_recovery_workbench_s213_ready_report_only"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "current_story_id": CURRENT_STORY_ID,
        "generated_at": generated_at,
        "decision": decision,
        "inputs": {
            "s212_dir": rel_path(s212_dir),
            "atlas_db": rel_path(atlas_db),
            "source_url_db": rel_path(source_url_db),
            "allowed_archive_root_hash": hashlib.sha256(str(allowed_archive_root).encode("utf-8", errors="ignore")).hexdigest(),
        },
        "counts": counts,
        "artifacts": artifacts,
        "execution_cursor": {
            "next_story_id": "S214",
            "next_input": artifacts["s191_fetch_canary_queue_jsonl"] if s191_queue else artifacts["db2_source_provider_spool_jsonl"],
            "next_action": "Run S191 bounded no-cookie canary for resolved source URLs, then feed article-ready artifacts back into S193/S194 only if coverage passes; otherwise route unresolved rows to db2ctl JSONL spool/source-provider acquisition.",
            "db3_write_allowed_now": False,
            "db2_projection_allowed_now": False,
            "deploy_upload_review_release_allowed_now": False,
        },
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
    }
    write_json(out_dir / f"{REPORT_STEM}.json", report)
    write_scorecard(scorecard_path, report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s212-dir", type=Path, default=DEFAULT_S212_DIR)
    parser.add_argument("--atlas-db", type=Path, default=DEFAULT_ATLAS_DB)
    parser.add_argument("--source-url-db", type=Path, default=DEFAULT_SOURCE_URL_DB)
    parser.add_argument("--allowed-archive-root", type=Path, default=DEFAULT_ALLOWED_ARCHIVE_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--s191-limit", type=int, default=80)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_workbench(
        s212_dir=args.s212_dir,
        atlas_db=args.atlas_db,
        source_url_db=args.source_url_db,
        allowed_archive_root=args.allowed_archive_root,
        out_dir=args.out_dir,
        scorecard_path=args.scorecard,
        s191_limit=args.s191_limit,
    )
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "counts": report["counts"],
                "summary": report["artifacts"]["report_json"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if not report["safety"]["safety_findings"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
