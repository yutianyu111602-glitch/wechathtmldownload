#!/usr/bin/env python3
"""Atlas Swarm T6 Year-Context Dispatcher — parallel lane processor.

Reads the T6 blocked queues and dispatches N parallel read-only lanes
that cross-reference source article metadata against blocked rows to
narrow year candidates. All lanes are report-only; no DB writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import tempfile
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]

T6_REVIEW_DIR = STAGE7_ROOT / "reports" / "atlas_t6_time_title_year_context_review_20260527"
PROBE_DIR = STAGE7_ROOT / "reports" / "atlas_t6_year_context_source_artifact_probe_20260527"

DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_swarm_year_context_20260527"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_SWARM_YEAR_CONTEXT_20260527.md"

DEFAULT_ATLAS_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435"
    / "atlas.sqlite"
)

SCHEMA_VERSION = "stage7_atlas_t6_swarm_year_context_dispatcher.v1"
MAX_WORKERS = 6

URL_RE = re.compile(r"https?://|www\.", re.I)
SECRET_VALUE_RE = re.compile(r"api[_-]?key|authorization|bearer\s+[A-Za-z0-9._-]{12,}|pass_ticket=|openid=|token\s*[:=]|cookie\s*[:=]|password\s*[:=]", re.I)
LOCAL_PATH_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+", re.I)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = URL_RE.sub("[redacted_url]", text)
    text = LOCAL_PATH_RE.sub("[redacted_path]", text)
    return text[:limit].strip()


def short_hash(value: Any, length: int = 16) -> str:
    return hashlib.sha256(compact(value, 4000).encode("utf-8", errors="replace")).hexdigest()[:length]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            rows.append(json.loads(raw))
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)
    return len(rows)


def leak_scan(rows: list[dict[str, Any]]) -> dict[str, int]:
    hits: dict[str, int] = {"local_path_hits": 0, "public_url_hits": 0, "sensitive_key_hits": 0}

    def scan(value: Any) -> None:
        if isinstance(value, dict):
            for v in value.values():
                scan(v)
        elif isinstance(value, list):
            for v in value:
                scan(v)
        elif isinstance(value, str):
            hits["public_url_hits"] += len(URL_RE.findall(value))
            hits["local_path_hits"] += len(LOCAL_PATH_RE.findall(value))
            hits["sensitive_key_hits"] += len(SECRET_VALUE_RE.findall(value))

    for row in rows:
        scan(row)
    return hits


# ── Article metadata cache ────────────────────────────────────────────

def _build_article_uid_year_cache(atlas_db: Path) -> dict[str, int | None]:
    """Build a cache of article_uid hash → publish year from articles table."""
    cache: dict[str, int | None] = {}
    conn = sqlite3.connect(f"file:{atlas_db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='articles'")
        if not cur.fetchone():
            return cache
        cols = {row[1] for row in conn.execute("PRAGMA table_info(articles)")}
        year_col = None
        for candidate in ("publish_time", "source_archived_at", "post_date", "publish_date"):
            if candidate in cols:
                year_col = candidate
                break
        if not year_col:
            return cache
        need_cols = ["article_uid", year_col]
        available = [c for c in need_cols if c in cols]
        for row in conn.execute(f"SELECT {', '.join(available)} FROM articles"):
            uid = compact(row["article_uid"], 200) if "article_uid" in available else ""
            val = dict(row).get(year_col) or ""
            m = re.search(r"(20\d{2})", str(val))
            if uid and m:
                cache[short_hash(uid)] = int(m.group(1))
    finally:
        conn.close()
    return cache


def _build_account_year_distribution(atlas_db: Path) -> dict[str, Counter]:
    """Build per-source_account year distribution from articles table."""
    dist: dict[str, Counter] = defaultdict(Counter)
    conn = sqlite3.connect(f"file:{atlas_db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='articles'")
        if not cur.fetchone():
            return dist
        cols = {row[1] for row in conn.execute("PRAGMA table_info(articles)")}
        year_col = None
        for candidate in ("publish_time", "source_archived_at", "post_date", "publish_date"):
            if candidate in cols:
                year_col = candidate
                break
        if not year_col or "source_account" not in cols:
            return dist
        for row in conn.execute(f"SELECT source_account, {year_col} FROM articles"):
            acct = compact(row["source_account"], 240).casefold()
            val = dict(row).get(year_col) or ""
            m = re.search(r"(20\d{2})", str(val))
            if acct and m:
                dist[acct][int(m.group(1))] += 1
    finally:
        conn.close()
    return dist


def _build_article_year_cache(atlas_db: Path) -> dict[tuple[str, str], int | None]:
    """Build a memory cache of (source_account, title) → publish year."""
    cache: dict[tuple[str, str], int | None] = {}
    conn = sqlite3.connect(f"file:{atlas_db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='articles'")
        if not cur.fetchone():
            return cache
        # Check columns
        cols = {row[1] for row in conn.execute("PRAGMA table_info(articles)")}
        select_cols = ["source_account", "title"]
        if "publish_time" in cols:
            select_cols.append("publish_time")
        if "source_archived_at" in cols:
            select_cols.append("source_archived_at")
        if "post_date" in cols:
            select_cols.append("post_date")
        for row in conn.execute(f"SELECT {', '.join(select_cols)} FROM articles"):
            acct = compact(row["source_account"], 240).casefold()
            title = compact(row["title"], 600)
            year = None
            # Try publish_time first
            for col in ("publish_time", "source_archived_at", "post_date"):
                val = (dict(row).get(col) or "")
                if val:
                    m = re.search(r"(20\d{2})", str(val))
                    if m:
                        year = int(m.group(1))
                        break
            cache[(acct, title)] = year
    finally:
        conn.close()
    return cache


def _extract_year_from_text(text: str) -> int | None:
    m = re.search(r"(?<!\d)(20[01]\d|202[0-6])(?!\d)", text)
    return int(m.group(1)) if m else None


# ── Lane implementations ───────────────────────────────────────────────

def lane_weekday_year_narrow(
    rows: list[dict[str, Any]],
    article_year_cache: dict[tuple[str, str], int | None],
    account_year_dist: dict[str, Counter],
    generated_at: str,
) -> dict[str, Any]:
    """Lane B: Narrow weekday-year rows using article publish_time + account year distribution."""
    narrowed: list[dict[str, Any]] = []
    still_blocked: list[dict[str, Any]] = []
    candidate_ready: list[dict[str, Any]] = []

    for row in rows:
        diag = row.get("diagnostics", {})
        month_day = diag.get("month_day", "")
        possible_years = diag.get("possible_years", [])
        source_account = compact(row.get("source_account"), 240).casefold()
        source_title = compact(row.get("source_title"), 600)

        # Try article cache
        cache_key = (source_account, source_title)
        article_year = article_year_cache.get(cache_key)

        # Also try variants with stripped account prefix
        if article_year is None and "/" in source_account:
            short_acct = source_account.rsplit("/", 1)[-1].strip()
            article_year = article_year_cache.get((short_acct, source_title))

        # Try post_date from row
        post_year = _extract_year_from_text(row.get("post_date", "") or "")

        # Try year from source_title
        title_year = _extract_year_from_text(row.get("source_title", "") or "")

        # Try account year distribution — most common year for this account
        acct_years = account_year_dist.get(source_account)
        account_top_year = None
        account_year_confidence = 0.0
        if acct_years and possible_years:
            # Find the possible_year that has the highest count for this account
            scored = [(y, acct_years.get(y, 0)) for y in possible_years]
            scored.sort(key=lambda x: -x[1])
            if scored and scored[0][1] > 0:
                total = sum(scored[i][1] for i in range(len(scored)))
                account_top_year = scored[0][0]
                account_year_confidence = scored[0][1] / total if total > 0 else 0

        # Best year signal (prefer article-level evidence over account-level)
        best_year = article_year or post_year or title_year
        # Only use account-level if confidence is high
        if best_year is None and account_top_year and account_year_confidence >= 0.6:
            best_year = account_top_year

        narrowed_row = {
            "source_ref_id": compact(row.get("source_ref_id"), 160),
            "source_account": compact(row.get("source_account"), 240),
            "source_title": compact(row.get("source_title"), 600),
            "month_day": month_day,
            "weekday_context": compact(row.get("sample_time_texts"), 500),
            "possible_years": possible_years,
            "article_publish_year": article_year,
            "post_date_year": post_year,
            "title_year": title_year,
            "account_top_year": account_top_year,
            "account_year_confidence": round(account_year_confidence, 3),
            "account_year_dist_sample": dict(acct_years.most_common(5)) if acct_years else {},
            "best_year_signal": best_year,
            "year_narrowed": best_year is not None and best_year in possible_years,
            "narrowed_year": best_year if (best_year and best_year in possible_years) else None,
            "readback_gate_allowed_next": False,
            "write_gate_allowed_now": False,
            "source_raw_db_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
            "schema_version": f"{SCHEMA_VERSION}.weekday_year_row",
            "generated_at": generated_at,
        }

        if best_year and best_year in possible_years:
            narrowed_row["readback_gate_allowed_next"] = True
            narrowed_row["candidate_event_date"] = f"{best_year}-{month_day.replace('-', '-')}"
            candidate_ready.append(narrowed_row)
        elif best_year:
            narrowed.append(narrowed_row)
        else:
            still_blocked.append(narrowed_row)

    # Separate remaining narrowed rows (year signal exists but not in possible_years)
    remaining_narrowed = narrowed + still_blocked

    return {
        "lane": "weekday_year_narrow",
        "input_rows": len(rows),
        "candidate_ready_rows": len(candidate_ready),
        "narrowed_rows": len(narrowed),
        "still_blocked_rows": len(still_blocked),
        "candidate_ready": candidate_ready,
        "remaining": remaining_narrowed,
    }


def lane_bound_missing_year_deep_dive(
    rows: list[dict[str, Any]],
    article_uid_year_cache: dict[str, int | None],
    generated_at: str,
) -> dict[str, Any]:
    """Lane C: 99 bound-but-missing-year rows — resolve year via article_uid cache."""
    resolved: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for row in rows:
        source_account = compact(row.get("source_account"), 240).casefold()
        source_title = compact(row.get("source_title"), 600)

        # Use article_uid hash from probe to look up publish year
        article_uid_hash = row.get("article_uid_ref", "")
        article_year = article_uid_year_cache.get(article_uid_hash) if article_uid_hash else None

        result = {
            "source_ref_id": compact(row.get("source_ref_id"), 160),
            "source_account": compact(row.get("source_account"), 240),
            "source_title": compact(row.get("source_title"), 600),
            "article_publish_year": article_year,
            "local_year_context_values": row.get("local_year_context_values", []),
            "month_day_candidates": row.get("month_day_candidates", []),
            "binding_status": row.get("binding_status", ""),
            "article_match_count": row.get("article_match_count", 0),
            "year_resolved": article_year is not None,
            "resolved_year": article_year,
            "readback_gate_allowed_next": False,
            "write_gate_allowed_now": False,
            "source_raw_db_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
            "schema_version": f"{SCHEMA_VERSION}.bound_missing_year_row",
            "generated_at": generated_at,
        }
        if article_year:
            resolved.append(result)
        else:
            unresolved.append(result)

    return {
        "lane": "bound_missing_year_deep_dive",
        "input_rows": len(rows),
        "resolved_rows": len(resolved),
        "unresolved_rows": len(unresolved),
        "resolved": resolved,
        "unresolved": unresolved,
    }


def lane_conflict_triage(
    rows: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    """Lane D: Triage conflict/ambiguous rows by conflict type."""
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        status = compact(row.get("review_status") or row.get("blocked_reason"), 160)
        by_type[status].append(row)

    triage = []
    for status_type, group in sorted(by_type.items()):
        triage.append({
            "conflict_type": status_type,
            "row_count": len(group),
            "sample_source_ref_ids": [compact(r.get("source_ref_id"), 80) for r in group[:3]],
            "sample_titles": [compact(r.get("source_title"), 120) for r in group[:3]],
        })

    return {
        "lane": "conflict_triage",
        "input_rows": len(rows),
        "conflict_types": len(by_type),
        "triage": triage,
    }


# ── Dispatcher ─────────────────────────────────────────────────────────

def dispatch_swarm(
    weekday_rows: list[dict[str, Any]] | None,
    bound_missing_rows: list[dict[str, Any]] | None,
    conflict_rows: list[dict[str, Any]] | None,
    atlas_db: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    generated_at = now_iso()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build shared caches (single-threaded SQLite reads)
    t0 = time.monotonic()
    article_uid_year_cache = _build_article_uid_year_cache(atlas_db)
    account_year_dist = _build_account_year_distribution(atlas_db)
    article_year_cache = _build_article_year_cache(atlas_db)
    cache_time = time.monotonic() - t0

    lanes: list[tuple[str, Any, Any, Any]] = []

    if weekday_rows:
        lanes.append(("weekday_year_narrow", weekday_rows, article_year_cache, account_year_dist))
    if bound_missing_rows:
        lanes.append(("bound_missing_year_deep_dive", bound_missing_rows, article_uid_year_cache, None))
    if conflict_rows:
        lanes.append(("conflict_triage", conflict_rows, None, None))

    lane_results: dict[str, Any] = {}
    lane_outputs: dict[str, list[dict[str, Any]]] = {}

    if len(lanes) <= 1:
        # Sequential for single lane
        for name, data, cache1, cache2 in lanes:
            if name == "weekday_year_narrow":
                result = lane_weekday_year_narrow(data, cache1, cache2, generated_at)
            elif name == "bound_missing_year_deep_dive":
                result = lane_bound_missing_year_deep_dive(data, cache1, generated_at)
            elif name == "conflict_triage":
                result = lane_conflict_triage(data, generated_at)
            else:
                continue
            lane_results[name] = result
            _write_lane_outputs(name, result, out_dir, lane_outputs)
    else:
        # Parallel dispatch
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(lanes))) as executor:
            futures: dict[Any, str] = {}
            for name, data, cache1, cache2 in lanes:
                if name == "weekday_year_narrow":
                    fut = executor.submit(lane_weekday_year_narrow, data, cache1, cache2, generated_at)
                elif name == "bound_missing_year_deep_dive":
                    fut = executor.submit(lane_bound_missing_year_deep_dive, data, cache1, generated_at)
                elif name == "conflict_triage":
                    fut = executor.submit(lane_conflict_triage, data, generated_at)
                else:
                    continue
                futures[fut] = name

            for fut in as_completed(futures):
                name = futures[fut]
                result = fut.result()
                lane_results[name] = result
                _write_lane_outputs(name, result, out_dir, lane_outputs)

    # Aggregate
    total_input = sum(r.get("input_rows", 0) for r in lane_results.values())
    total_candidate_ready = sum(
        r.get("candidate_ready_rows", 0) + r.get("resolved_rows", 0)
        for r in lane_results.values()
    )
    total_still_blocked = (
        sum(r.get("still_blocked_rows", 0) for r in lane_results.values())
        + sum(r.get("unresolved_rows", 0) for r in lane_results.values())
        + sum(r.get("narrowed_rows", 0) for r in lane_results.values())
    )

    decision = (
        "atlas_t6_swarm_year_context_candidates_ready_report_only"
        if total_candidate_ready > 0
        else "atlas_t6_swarm_year_context_blocked_report_only"
    )

    # Write aggregated outputs
    all_ready: list[dict[str, Any]] = []
    for name, result in lane_results.items():
        if "candidate_ready" in result:
            all_ready.extend(result["candidate_ready"])
        if "resolved" in result:
            all_ready.extend(result["resolved"])

    if all_ready:
        write_jsonl(out_dir / "swarm_candidate_ready_report_only.jsonl", all_ready)

    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": [],
        "article_cache_build_time_seconds": round(cache_time, 2),
        "article_uid_cache_entries": len(article_uid_year_cache),
        "account_year_dist_accounts": len(account_year_dist),
        "article_title_cache_entries": len(article_year_cache),
        "lane_count": len(lanes),
        "lane_results": {
            name: {
                k: v
                for k, v in result.items()
                if k not in ("candidate_ready", "resolved", "unresolved", "remaining", "triage")
            }
            for name, result in lane_results.items()
        },
        "counts": {
            "total_input_rows": total_input,
            "total_candidate_ready_rows": total_candidate_ready,
            "total_still_blocked_rows": total_still_blocked,
            "graph_write_allowed_rows": 0,
            "memory_write_allowed_rows": 0,
            "public_serving_field_allowed_rows": 0,
            "serving_rebuild_allowed_rows": 0,
            "source_raw_db_write_allowed_rows": 0,
            "write_execution_allowed_rows": 0,
        },
        "outputs": lane_outputs,
        "boundary_truth": {
            "report_only": True,
            "source_raw_db_write_executed": False,
            "serving_sqlite_write_or_rebuild_executed": False,
            "graph_write_executed": False,
            "qdrant_write_executed": False,
            "production_sqlite_write_executed": False,
            "public_pointer_updated": False,
            "huaidj_club_upload_executed": False,
            "cloudrun_deploy_executed": False,
            "vps_deploy_executed": False,
            "mini_program_upload_or_review_executed": False,
            "memory_write_executed": False,
            "network_fetch_executed": False,
            "model_call_executed": False,
            "ocr_executed": False,
        },
        "next_resume_pointer": (
            str(out_dir / "swarm_candidate_ready_report_only.jsonl")
            if all_ready
            else str(out_dir / "swarm_summary.json")
        ),
    }

    # Leak scan
    all_output_rows: list[dict[str, Any]] = all_ready.copy() if all_ready else []
    summary["leak_scan"] = leak_scan(all_output_rows)

    write_json(out_dir / "swarm_summary.json", summary)

    # Write report
    report_text = _render_report(summary, lane_results)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=report_path.parent, delete=False, newline="\n") as handle:
        handle.write(report_text)
        tmp = Path(handle.name)
    tmp.replace(report_path)

    return summary


def _write_lane_outputs(name: str, result: dict[str, Any], out_dir: Path, lane_outputs: dict[str, list[dict[str, Any]]]) -> None:
    lane_dir = out_dir / f"lane_{name}"
    lane_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {}

    if "candidate_ready" in result and result["candidate_ready"]:
        path = lane_dir / "candidate_ready.jsonl"
        write_jsonl(path, result["candidate_ready"])
        outputs["candidate_ready"] = str(path.relative_to(REPO_ROOT)).replace("\\", "/")

    if "resolved" in result and result["resolved"]:
        path = lane_dir / "resolved.jsonl"
        write_jsonl(path, result["resolved"])
        outputs["resolved"] = str(path.relative_to(REPO_ROOT)).replace("\\", "/")

    if "unresolved" in result and result["unresolved"]:
        path = lane_dir / "unresolved.jsonl"
        write_jsonl(path, result["unresolved"])
        outputs["unresolved"] = str(path.relative_to(REPO_ROOT)).replace("\\", "/")

    if "remaining" in result and result["remaining"]:
        path = lane_dir / "remaining.jsonl"
        write_jsonl(path, result["remaining"])
        outputs["remaining"] = str(path.relative_to(REPO_ROOT)).replace("\\", "/")

    lane_outputs[name] = outputs


def _render_report(summary: dict[str, Any], lane_results: dict[str, Any]) -> str:
    c = summary["counts"]
    lanes_text = ""
    for name, result in lane_results.items():
        lanes_text += f"\n### Lane: {name}\n\n"
        for k, v in result.items():
            if k not in ("candidate_ready", "resolved", "unresolved", "remaining", "triage"):
                lanes_text += f"- {k}: `{v}`\n"

    return "\n".join([
        "# Atlas T6 Swarm Year-Context Dispatcher - 2026-05-27",
        "",
        "## Decision",
        f"`{summary['decision']}`",
        "",
        "## Swarm Architecture",
        "",
        "Parallel read-only lanes dispatched via ThreadPoolExecutor. Each lane cross-references blocked T6 year-context rows against source article metadata (publish_time, source_archived_at, post_date) from the atlas DB. All lanes are report-only; no DB writes.",
        "",
        "## Aggregate Counts",
        f"- Lanes dispatched: `{summary['lane_count']}`",
        f"- Total input rows: `{c['total_input_rows']}`",
        f"- Candidate-ready rows: `{c['total_candidate_ready_rows']}`",
        f"- Still blocked rows: `{c['total_still_blocked_rows']}`",
        f"- Article UID cache entries: `{summary['article_uid_cache_entries']}`",
        f"- Account year dist accounts: `{summary['account_year_dist_accounts']}`",
        f"- Article title cache entries: `{summary['article_title_cache_entries']}`",
        f"- Cache build time: `{summary['article_cache_build_time_seconds']}s`",
        f"- Write allowed rows: `{c['write_execution_allowed_rows']}`",
        "",
        "## Leak Scan",
        f"- public URL / sensitive key / local path hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['sensitive_key_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Boundary Truth",
        "- No source/raw DB, serving SQLite, graph, vector, public pointer, huaidj.club, CloudRun, mini-program, memory, network, OCR, or model writes.",
        "",
        "## Lane Details",
        lanes_text,
        "",
        "## Next Resume Pointer",
        f"`{summary['next_resume_pointer']}`",
    ])


# ── CLI ─────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Atlas Swarm T6 Year-Context Dispatcher")
    parser.add_argument("--weekday-input", type=Path,
                        default=T6_REVIEW_DIR / "year_context_weekday_review_required_rows.jsonl")
    parser.add_argument("--bound-missing-input", type=Path,
                        default=PROBE_DIR / "year_context_source_artifact_bound_missing_year_rows.jsonl")
    parser.add_argument("--conflict-input", type=Path,
                        default=T6_REVIEW_DIR / "year_context_conflict_or_ambiguous_rows.jsonl")
    parser.add_argument("--atlas-db", type=Path, default=DEFAULT_ATLAS_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--lanes", type=str, default="weekday,bound_missing",
                        help="Comma-separated lanes to run: weekday,bound_missing,conflict")
    args = parser.parse_args()

    active_lanes = {x.strip() for x in args.lanes.split(",")}

    weekday_rows = read_jsonl(args.weekday_input) if "weekday" in active_lanes and args.weekday_input.exists() else None
    bound_missing_rows = read_jsonl(args.bound_missing_input) if "bound_missing" in active_lanes and args.bound_missing_input.exists() else None
    conflict_rows = read_jsonl(args.conflict_input) if "conflict" in active_lanes and args.conflict_input.exists() else None

    if not any([weekday_rows, bound_missing_rows, conflict_rows]):
        print("ERROR: No input rows loaded for any active lane", flush=True)
        return 1

    print(f"Swarm dispatch: weekday={len(weekday_rows) if weekday_rows else 0}, "
          f"bound_missing={len(bound_missing_rows) if bound_missing_rows else 0}, "
          f"conflict={len(conflict_rows) if conflict_rows else 0}", flush=True)

    summary = dispatch_swarm(
        weekday_rows=weekday_rows,
        bound_missing_rows=bound_missing_rows,
        conflict_rows=conflict_rows,
        atlas_db=args.atlas_db,
        out_dir=args.out_dir,
        report_path=args.report,
    )

    print(json.dumps({
        "decision": summary["decision"],
        "candidate_ready": summary["counts"]["total_candidate_ready_rows"],
        "still_blocked": summary["counts"]["total_still_blocked_rows"],
    }, ensure_ascii=False))
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
