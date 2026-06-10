#!/usr/bin/env python3
"""Build a report-only search/graph smoke for the T5 serving time overlay.

The time overlay candidate updates report-local `starts_at` fields without
refreshing event search documents. This smoke validates direct readback from
the candidate DB, graph-window coverage for affected DJs, and records the
date-search refresh boundary as a separate gate before any public promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OVERLAY_SUMMARY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t5_serving_time_overlay_candidate_20260527"
    / "serving_time_overlay_summary.json"
)
DEFAULT_CHANGED_ROWS = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t5_serving_time_overlay_candidate_20260527"
    / "serving_time_overlay_changed_rows.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t5_serving_time_overlay_search_graph_smoke_20260527"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "ATLAS_T5_SERVING_TIME_OVERLAY_SEARCH_GRAPH_SMOKE_20260527.md"
DEFAULT_API_SMOKE = REPO_ROOT / "reports" / "atlas_serving_time_overlay_local_smoke_20260527_0929" / "api_smoke.json"
DEFAULT_BROWSER_SMOKE = REPO_ROOT / "reports" / "atlas_serving_time_overlay_local_smoke_20260527_0929" / "browser_smoke.json"
SHANGHAI_TZ = timezone(timedelta(hours=8))
PUBLIC_URL_RE = re.compile(r"https?://|mp\.weixin\.qq\.com|wx\.qq\.com", re.IGNORECASE)
LOCAL_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|\\\\wsl|/mnt/|/home/)", re.IGNORECASE)
SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|secret|password|access[_-]?token|refresh[_-]?token|cookie|openid|unionid|fakeid)\s*[:=]",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).replace(microsecond=0).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT)).replace("/", "\\")
    except ValueError:
        return f"<external_path_hash:{hashlib.sha256(str(path).encode('utf-8')).hexdigest()[:16]}>"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return read_json(path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            value = json.loads(text)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no} is not a JSON object")
            rows.append(value)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def chunked(values: list[str], size: int = 500) -> Iterable[list[str]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ? AND type IN ('table', 'view')",
        (table,),
    ).fetchone()
    return bool(row)


def table_count(conn: sqlite3.Connection, table: str) -> int | None:
    if not table_exists(conn, table):
        return None
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def blank_count(conn: sqlite3.Connection, table: str, column: str) -> int | None:
    if not table_exists(conn, table):
        return None
    return int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL OR trim({column}) = ''").fetchone()[0])


def event_date_tokens(date_value: str) -> set[str]:
    date_value = str(date_value or "").strip()
    if not date_value:
        return set()
    parts = date_value.split("-")
    if len(parts) != 3:
        return {date_value}
    year, month, day = parts
    return {
        date_value,
        f"{year}/{int(month)}/{int(day)}",
        f"{int(month)}.{int(day):02d}",
        f"{int(month)}.{int(day)}",
        f"{int(month)}/{int(day)}",
        f"{int(month)}月{int(day)}日",
    }


def readback_performance_events(
    conn: sqlite3.Connection,
    rows: list[dict[str, Any]],
    sample_limit: int,
) -> tuple[dict[str, int], list[dict[str, Any]], list[dict[str, Any]]]:
    expected = {str(row["event_id"]): str(row["proposed_starts_at"]) for row in rows}
    found: dict[str, sqlite3.Row] = {}
    for batch in chunked(sorted(expected)):
        placeholders = ",".join("?" for _ in batch)
        for row in conn.execute(
            f"""
            SELECT event_id, event_title, starts_at, time_text, city, venue_name
            FROM performance_event
            WHERE event_id IN ({placeholders})
            """,
            batch,
        ):
            found[str(row["event_id"])] = row

    counts = Counter()
    samples: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for event_id, proposed in expected.items():
        row = found.get(event_id)
        if not row:
            counts["performance_event_missing_rows"] += 1
            failed.append({"target_table": "performance_event", "event_id": event_id, "reason": "performance_event_missing"})
            continue
        starts_at = str(row["starts_at"] or "")
        if starts_at == proposed:
            counts["performance_event_starts_at_match_rows"] += 1
        else:
            counts["performance_event_starts_at_mismatch_rows"] += 1
            failed.append(
                {
                    "target_table": "performance_event",
                    "event_id": event_id,
                    "expected_starts_at": proposed,
                    "actual_starts_at": starts_at,
                    "reason": "performance_event_starts_at_mismatch",
                }
            )
        if len(samples) < sample_limit:
            samples.append(
                {
                    "target_table": "performance_event",
                    "event_id": event_id,
                    "expected_starts_at": proposed,
                    "starts_at_matches": starts_at == proposed,
                    "event_title_hash": stable_hash(row["event_title"] or ""),
                    "time_text_hash": stable_hash(row["time_text"] or ""),
                    "venue_name_hash": stable_hash(row["venue_name"] or ""),
                }
            )
    counts["performance_event_rows_checked"] = len(expected)
    return dict(counts), samples, failed


def readback_dj_events(
    conn: sqlite3.Connection,
    rows: list[dict[str, Any]],
    sample_limit: int,
) -> tuple[dict[str, int], list[dict[str, Any]], list[dict[str, Any]]]:
    expected = {
        (str(row["dj_id"]), str(row["event_id"])): str(row["proposed_starts_at"])
        for row in rows
        if row.get("dj_id") and row.get("event_id")
    }
    event_ids = sorted({event_id for _dj_id, event_id in expected})
    found: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    for batch in chunked(event_ids):
        placeholders = ",".join("?" for _ in batch)
        for row in conn.execute(
            f"""
            SELECT dj_id, event_id, starts_at, time_text, city, venue_name
            FROM dj_event
            WHERE event_id IN ({placeholders})
            """,
            batch,
        ):
            key = (str(row["dj_id"]), str(row["event_id"]))
            if key in expected:
                found[key].append(row)

    counts = Counter()
    samples: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for key, proposed in expected.items():
        dj_id, event_id = key
        rows_for_key = found.get(key, [])
        if not rows_for_key:
            counts["dj_event_missing_rows"] += 1
            failed.append({"target_table": "dj_event", "dj_id": dj_id, "event_id": event_id, "reason": "dj_event_missing"})
            continue
        matching = [row for row in rows_for_key if str(row["starts_at"] or "") == proposed]
        conflicting = [row for row in rows_for_key if str(row["starts_at"] or "") not in {"", proposed}]
        if matching and not conflicting:
            counts["dj_event_starts_at_match_rows"] += 1
        else:
            if not matching:
                counts["dj_event_starts_at_missing_match_rows"] += 1
            if conflicting:
                counts["dj_event_starts_at_conflict_rows"] += 1
            failed.append(
                {
                    "target_table": "dj_event",
                    "dj_id": dj_id,
                    "event_id": event_id,
                    "expected_starts_at": proposed,
                    "matching_rows": len(matching),
                    "conflicting_rows": len(conflicting),
                    "reason": "dj_event_starts_at_readback_failed",
                }
            )
        if len(samples) < sample_limit:
            samples.append(
                {
                    "target_table": "dj_event",
                    "dj_id": dj_id,
                    "event_id": event_id,
                    "expected_starts_at": proposed,
                    "matching_rows": len(matching),
                    "conflicting_rows": len(conflicting),
                    "row_count": len(rows_for_key),
                    "sample_hash": stable_hash({"dj_id": dj_id, "event_id": event_id, "expected_starts_at": proposed}),
                }
            )
    counts["dj_event_rows_checked"] = len(expected)
    counts["dj_event_physical_rows_seen"] = sum(len(value) for value in found.values())
    return dict(counts), samples, failed


def search_document_smoke(
    conn: sqlite3.Connection,
    perf_rows: list[dict[str, Any]],
    sample_limit: int,
) -> tuple[dict[str, int], list[dict[str, Any]], list[dict[str, Any]]]:
    expected = {str(row["event_id"]): str(row["proposed_starts_at"]) for row in perf_rows}
    docs: dict[str, sqlite3.Row] = {}
    for batch in chunked(sorted(expected)):
        placeholders = ",".join("?" for _ in batch)
        for row in conn.execute(
            f"""
            SELECT doc_rowid, subject_id, display_name, city_text, search_text
            FROM search_document
            WHERE subject_type = 'event' AND subject_id IN ({placeholders})
            """,
            batch,
        ):
            docs[str(row["subject_id"])] = row

    counts = Counter()
    samples: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for event_id, proposed in expected.items():
        doc = docs.get(event_id)
        if not doc:
            counts["event_search_document_missing_rows"] += 1
            failed.append({"event_id": event_id, "reason": "event_search_document_missing"})
            continue
        search_text = str(doc["search_text"] or "")
        display_name = str(doc["display_name"] or "")
        date_match = any(token and token in search_text for token in event_date_tokens(proposed))
        title_match = bool(display_name and display_name in search_text)
        counts["event_search_document_rows"] += 1
        if date_match:
            counts["event_search_text_has_date_rows"] += 1
        else:
            counts["event_search_text_missing_date_rows"] += 1
        if title_match:
            counts["event_search_text_has_title_rows"] += 1
        if len(samples) < sample_limit:
            samples.append(
                {
                    "event_id": event_id,
                    "doc_rowid": int(doc["doc_rowid"]),
                    "expected_starts_at": proposed,
                    "search_text_has_date": date_match,
                    "search_text_has_title": title_match,
                    "display_name_hash": stable_hash(display_name),
                    "city_text_hash": stable_hash(doc["city_text"] or ""),
                }
            )
    counts["event_search_rows_checked"] = len(expected)
    return dict(counts), samples, failed


def graph_window_smoke(
    conn: sqlite3.Connection,
    dj_rows: list[dict[str, Any]],
    sample_limit: int,
) -> tuple[dict[str, int], list[dict[str, Any]], list[dict[str, Any]]]:
    affected_djs = sorted({str(row["dj_id"]) for row in dj_rows if row.get("dj_id")})
    seed_rows: set[str] = set()
    if affected_djs and table_exists(conn, "graph_window_cache"):
        for batch in chunked(affected_djs):
            placeholders = ",".join("?" for _ in batch)
            for row in conn.execute(
                f"SELECT seed_subject_id FROM graph_window_cache WHERE seed_subject_id IN ({placeholders})",
                batch,
            ):
                seed_rows.add(str(row["seed_subject_id"]))
    missing = sorted(set(affected_djs) - seed_rows)
    samples = [
        {
            "dj_id": dj_id,
            "graph_window_present": dj_id in seed_rows,
            "sample_hash": stable_hash({"dj_id": dj_id, "graph_window_present": dj_id in seed_rows}),
        }
        for dj_id in affected_djs[:sample_limit]
    ]
    failed = [{"dj_id": dj_id, "reason": "graph_window_seed_missing"} for dj_id in missing[:sample_limit]]
    return (
        {
            "graph_window_dj_seeds_checked": len(affected_djs),
            "graph_window_seed_rows": len(seed_rows),
            "graph_window_missing_seed_rows": len(missing),
        },
        samples,
        failed,
    )


def metric_readback(conn: sqlite3.Connection, summary: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    after = summary.get("metrics", {}).get("after", {})
    expected_counts = after.get("table_counts", {})
    expected_gaps = after.get("field_gaps", {})
    actual_counts = {table: table_count(conn, table) for table in expected_counts}
    actual_gaps = {
        "performance_event": {
            "city_gap": blank_count(conn, "performance_event", "city"),
            "starts_at_gap": blank_count(conn, "performance_event", "starts_at"),
        },
        "dj_event": {
            "city_gap": blank_count(conn, "dj_event", "city"),
            "starts_at_gap": blank_count(conn, "dj_event", "starts_at"),
        },
    }
    drift: list[dict[str, Any]] = []
    for table, expected in expected_counts.items():
        if actual_counts.get(table) != expected:
            drift.append({"kind": "table_count_drift", "table": table, "expected": expected, "actual": actual_counts.get(table)})
    for table, gaps in expected_gaps.items():
        for field in ("city_gap", "starts_at_gap"):
            if table in actual_gaps and actual_gaps[table].get(field) != gaps.get(field):
                drift.append(
                    {
                        "kind": "field_gap_drift",
                        "table": table,
                        "field": field,
                        "expected": gaps.get(field),
                        "actual": actual_gaps[table].get(field),
                    }
                )
    return {"table_counts": actual_counts, "field_gaps": actual_gaps}, drift


def smoke_rollup(api_smoke_path: Path, browser_smoke_path: Path) -> dict[str, Any]:
    api = read_json_if_exists(api_smoke_path)
    browser = read_json_if_exists(browser_smoke_path)
    return {
        "api_smoke_present": api is not None,
        "api_smoke_ok": bool(api.get("ok")) if api else False,
        "api_failed_checks": api.get("failed_api_checks", []) if api else [],
        "browser_smoke_present": browser is not None,
        "browser_smoke_ok": bool(browser.get("ok")) if browser else False,
        "browser_failed_checks": browser.get("failed_browser_checks", []) if browser else [],
    }


def leak_scan(value: Any) -> dict[str, int]:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return {
        "public_url_hits": len(PUBLIC_URL_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
        "sensitive_key_hits": len(SENSITIVE_KEY_RE.findall(text)),
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    c = report["counts"]
    boundary = report["boundary_truth"]
    lines = [
        "# Atlas T5 Serving Time Overlay Search/Graph Smoke",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Decision",
        "",
        f"`{report['decision']}`",
        "",
        f"Failed checks: `{report['failed_checks']}`",
        "",
        "This is report-local/read-only evidence for the serving time overlay candidate. It does not mutate selected serving SQLite, source/raw SQLite, graph/vector stores, public pointers, huaidj.club, CloudRun/VPS, mini-program state, or memory.",
        "",
        "## Counts",
        "",
        f"- changed rows input: `{c['changed_rows_input']}` split performance_event/dj_event `{c['performance_event_changed_rows_input']}` / `{c['dj_event_changed_rows_input']}`",
        f"- performance_event readback match/missing/mismatch: `{c['performance_event_starts_at_match_rows']}` / `{c['performance_event_missing_rows']}` / `{c['performance_event_starts_at_mismatch_rows']}`",
        f"- dj_event readback match/missing/conflict: `{c['dj_event_starts_at_match_rows']}` / `{c['dj_event_missing_rows']}` / `{c['dj_event_starts_at_conflict_rows']}`",
        f"- event search docs present/missing/date-missing: `{c['event_search_document_rows']}` / `{c['event_search_document_missing_rows']}` / `{c['event_search_text_missing_date_rows']}`",
        f"- graph window seeds / missing seeds: `{c['graph_window_seed_rows']}` / `{c['graph_window_missing_seed_rows']}`",
        f"- table/field metric drift rows: `{c['metric_drift_rows']}`",
        f"- search-date refresh required rows: `{c['search_date_refresh_required_rows']}`",
        f"- local API/browser smoke ok: `{str(report['local_smoke']['api_smoke_ok']).lower()}` / `{str(report['local_smoke']['browser_smoke_ok']).lower()}`",
        f"- leak hits public URL / local path / sensitive key: `{report['leak_scan']['public_url_hits']}` / `{report['leak_scan']['local_path_hits']}` / `{report['leak_scan']['sensitive_key_hits']}`",
        "",
        "## Boundary Truth",
        "",
    ]
    for key, value in boundary.items():
        lines.append(f"- {key}: `{str(value).lower() if isinstance(value, bool) else value}`")
    lines.extend(["", "## Outputs", ""])
    for key, value in report["outputs"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Next Resume Pointer", "", report["next_resume_pointer"], ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def build_smoke(
    *,
    overlay_summary: Path,
    changed_rows_path: Path,
    candidate_db: Path | None,
    out_dir: Path,
    report_path: Path,
    api_smoke_path: Path,
    browser_smoke_path: Path,
    sample_limit: int = 200,
) -> dict[str, Any]:
    summary = read_json(overlay_summary)
    changed_rows = read_jsonl(changed_rows_path)
    resolved_candidate = candidate_db or (REPO_ROOT / summary["outputs"]["candidate_db"])
    perf_rows = [row for row in changed_rows if row.get("target_table") == "performance_event"]
    dj_rows = [row for row in changed_rows if row.get("target_table") == "dj_event"]
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = connect_readonly(resolved_candidate)
    try:
        perf_counts, perf_samples, perf_failures = readback_performance_events(conn, perf_rows, sample_limit)
        dj_counts, dj_samples, dj_failures = readback_dj_events(conn, dj_rows, sample_limit)
        search_counts, search_samples, search_failures = search_document_smoke(conn, perf_rows, sample_limit)
        graph_counts, graph_samples, graph_failures = graph_window_smoke(conn, dj_rows, sample_limit)
        metrics, metric_drift = metric_readback(conn, summary)
    finally:
        conn.close()

    local_smoke = smoke_rollup(api_smoke_path, browser_smoke_path)
    failed_checks: list[str] = []
    if perf_failures:
        failed_checks.append("performance_event_starts_at_readback_failed")
    if dj_failures:
        failed_checks.append("dj_event_starts_at_readback_failed")
    if search_failures:
        failed_checks.append("event_search_document_missing")
    if graph_counts.get("graph_window_missing_seed_rows", 0):
        failed_checks.append("graph_window_seed_missing")
    if metric_drift:
        failed_checks.append("candidate_metric_drift")
    if local_smoke["api_smoke_present"] and not local_smoke["api_smoke_ok"]:
        failed_checks.append("local_api_smoke_failed")
    if local_smoke["browser_smoke_present"] and not local_smoke["browser_smoke_ok"]:
        failed_checks.append("local_browser_smoke_failed")

    search_date_refresh_required = int(summary.get("counts", {}).get("search_date_refresh_deferred_rows", 0))
    counts = {
        "changed_rows_input": len(changed_rows),
        "performance_event_changed_rows_input": len(perf_rows),
        "dj_event_changed_rows_input": len(dj_rows),
        "candidate_db_opened_read_only": 1,
        "performance_event_rows_checked": perf_counts.get("performance_event_rows_checked", 0),
        "performance_event_starts_at_match_rows": perf_counts.get("performance_event_starts_at_match_rows", 0),
        "performance_event_missing_rows": perf_counts.get("performance_event_missing_rows", 0),
        "performance_event_starts_at_mismatch_rows": perf_counts.get("performance_event_starts_at_mismatch_rows", 0),
        "dj_event_rows_checked": dj_counts.get("dj_event_rows_checked", 0),
        "dj_event_physical_rows_seen": dj_counts.get("dj_event_physical_rows_seen", 0),
        "dj_event_starts_at_match_rows": dj_counts.get("dj_event_starts_at_match_rows", 0),
        "dj_event_missing_rows": dj_counts.get("dj_event_missing_rows", 0),
        "dj_event_starts_at_missing_match_rows": dj_counts.get("dj_event_starts_at_missing_match_rows", 0),
        "dj_event_starts_at_conflict_rows": dj_counts.get("dj_event_starts_at_conflict_rows", 0),
        "event_search_rows_checked": search_counts.get("event_search_rows_checked", 0),
        "event_search_document_rows": search_counts.get("event_search_document_rows", 0),
        "event_search_document_missing_rows": search_counts.get("event_search_document_missing_rows", 0),
        "event_search_text_has_date_rows": search_counts.get("event_search_text_has_date_rows", 0),
        "event_search_text_missing_date_rows": search_counts.get("event_search_text_missing_date_rows", 0),
        "event_search_text_has_title_rows": search_counts.get("event_search_text_has_title_rows", 0),
        "graph_window_dj_seeds_checked": graph_counts.get("graph_window_dj_seeds_checked", 0),
        "graph_window_seed_rows": graph_counts.get("graph_window_seed_rows", 0),
        "graph_window_missing_seed_rows": graph_counts.get("graph_window_missing_seed_rows", 0),
        "metric_drift_rows": len(metric_drift),
        "search_date_refresh_required_rows": search_date_refresh_required,
        "source_sqlite_write_rows": 0,
        "serving_rebuild_rows": 0,
        "graph_write_rows": 0,
        "public_serving_field_rows": 0,
        "memory_write_rows": 0,
    }
    decision = (
        "atlas_t5_serving_time_overlay_search_graph_smoke_blocked_report_only"
        if failed_checks
        else "atlas_t5_serving_time_overlay_search_graph_smoke_ready_search_date_refresh_required_report_only"
        if search_date_refresh_required
        else "atlas_t5_serving_time_overlay_search_graph_smoke_ready_report_only"
    )
    outputs = {
        "summary_json": rel(out_dir / "serving_time_overlay_search_graph_smoke_summary.json"),
        "event_readback_samples": rel(out_dir / "serving_time_overlay_event_readback_samples.jsonl"),
        "dj_event_readback_samples": rel(out_dir / "serving_time_overlay_dj_event_readback_samples.jsonl"),
        "search_samples": rel(out_dir / "serving_time_overlay_search_samples.jsonl"),
        "graph_samples": rel(out_dir / "serving_time_overlay_graph_samples.jsonl"),
        "failed_rows": rel(out_dir / "serving_time_overlay_smoke_failed_rows.jsonl"),
        "api_contract": rel(out_dir / "serving_time_overlay_api_contract.json"),
        "report": rel(report_path),
    }
    boundary_truth = {
        "candidate_serving_db_opened_read_only": True,
        "source_raw_db_opened": False,
        "source_raw_db_write_executed": False,
        "selected_serving_db_mutated": False,
        "serving_rebuild_executed": False,
        "graph_vector_public_mutation_executed": False,
        "public_pointer_updated": False,
        "huaidj_club_upload_executed": False,
        "cloudrun_or_vps_deploy_executed": False,
        "mini_program_upload_or_review_executed": False,
        "network_ocr_model_memory_executed": False,
        "deployable_public": False,
    }
    api_contract = {
        "schema_version": "stage7_atlas_t5_serving_time_overlay_api_contract.v1",
        "candidate_db": rel(resolved_candidate),
        "routes": {
            "event_time_detail": {"source": outputs["event_readback_samples"], "status": "ready_report_only"},
            "dj_event_time_edges": {"source": outputs["dj_event_readback_samples"], "status": "ready_report_only"},
            "event_search_date": {"source": outputs["search_samples"], "status": "refresh_required_before_public"},
            "dj_graph_windows": {"source": outputs["graph_samples"], "status": "ready_report_only"},
        },
        "public_serving_approved": False,
    }
    report = {
        "schema_version": "stage7_atlas_t5_serving_time_overlay_search_graph_smoke.v1.summary",
        "generated_at": now_iso(),
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {
            "overlay_summary": rel(overlay_summary),
            "changed_rows": rel(changed_rows_path),
            "candidate_db": rel(resolved_candidate),
            "api_smoke": rel(api_smoke_path),
            "browser_smoke": rel(browser_smoke_path),
        },
        "counts": counts,
        "metrics_readback": metrics,
        "metric_drift_rows": metric_drift,
        "local_smoke": local_smoke,
        "leak_scan": {"public_url_hits": 0, "local_path_hits": 0, "sensitive_key_hits": 0},
        "boundary_truth": boundary_truth,
        "outputs": outputs,
        "next_resume_pointer": (
            "tools\\stage7_rewrite\\reports\\atlas_t5_serving_time_overlay_search_graph_smoke_20260527\\"
            "serving_time_overlay_search_graph_smoke_summary.json. "
            "Next: build a bounded search-date refresh/package preflight for the 394 deferred event search rows before any public serving promotion; "
            "if public upload remains disabled, continue span_or_range_review_required_rows.jsonl or month_day_year_required_rows.jsonl."
        ),
    }
    combined_for_scan = {
        "report": report,
        "api_contract": api_contract,
        "event_samples": perf_samples,
        "dj_samples": dj_samples,
        "search_samples": search_samples,
        "graph_samples": graph_samples,
        "failed_rows": perf_failures + dj_failures + search_failures + graph_failures + metric_drift,
    }
    report["leak_scan"] = leak_scan(combined_for_scan)
    if any(report["leak_scan"].values()) and "leak_scan_hits_present" not in failed_checks:
        report["failed_checks"].append("leak_scan_hits_present")
        report["decision"] = "atlas_t5_serving_time_overlay_search_graph_smoke_blocked_report_only"

    write_jsonl(out_dir / "serving_time_overlay_event_readback_samples.jsonl", perf_samples)
    write_jsonl(out_dir / "serving_time_overlay_dj_event_readback_samples.jsonl", dj_samples)
    write_jsonl(out_dir / "serving_time_overlay_search_samples.jsonl", search_samples)
    write_jsonl(out_dir / "serving_time_overlay_graph_samples.jsonl", graph_samples)
    write_jsonl(out_dir / "serving_time_overlay_smoke_failed_rows.jsonl", perf_failures + dj_failures + search_failures + graph_failures + metric_drift)
    write_json(out_dir / "serving_time_overlay_api_contract.json", api_contract)
    write_json(out_dir / "serving_time_overlay_search_graph_smoke_summary.json", report)
    write_report(report_path, report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overlay-summary", type=Path, default=DEFAULT_OVERLAY_SUMMARY)
    parser.add_argument("--changed-rows", type=Path, default=DEFAULT_CHANGED_ROWS)
    parser.add_argument("--candidate-db", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--api-smoke", type=Path, default=DEFAULT_API_SMOKE)
    parser.add_argument("--browser-smoke", type=Path, default=DEFAULT_BROWSER_SMOKE)
    parser.add_argument("--sample-limit", type=int, default=200)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_smoke(
        overlay_summary=args.overlay_summary,
        changed_rows_path=args.changed_rows,
        candidate_db=args.candidate_db,
        out_dir=args.out_dir,
        report_path=args.report_path,
        api_smoke_path=args.api_smoke,
        browser_smoke_path=args.browser_smoke,
        sample_limit=args.sample_limit,
    )
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "failed_checks": report["failed_checks"],
                "summary_json": report["outputs"]["summary_json"],
                "report": report["outputs"]["report"],
                "performance_event_starts_at_match_rows": report["counts"]["performance_event_starts_at_match_rows"],
                "dj_event_starts_at_match_rows": report["counts"]["dj_event_starts_at_match_rows"],
                "search_date_refresh_required_rows": report["counts"]["search_date_refresh_required_rows"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
