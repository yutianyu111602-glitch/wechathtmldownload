#!/usr/bin/env python3
"""Build a report-only search/graph smoke for the T5 serving city overlay.

The city overlay candidate deliberately updates event search rows without
refreshing FTS. This smoke validates the direct read-model/search_document and
graph-window contract, while keeping the FTS refresh as an explicit follow-up
gate instead of silently treating the candidate as public-deployable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = SCRIPT_DIR.parent

DEFAULT_OVERLAY_SUMMARY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t5_serving_city_overlay_candidate_20260527"
    / "serving_city_overlay_summary.json"
)
DEFAULT_OVERLAY_SEARCH_ROWS = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t5_serving_city_overlay_candidate_20260527"
    / "serving_city_overlay_search_document_rows.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t5_serving_city_overlay_search_graph_smoke_20260527"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "ATLAS_T5_SERVING_CITY_OVERLAY_SEARCH_GRAPH_SMOKE_20260527.md"

PUBLIC_URL_RE = re.compile(r"https?://|mp\.weixin\.qq\.com|wx\.qq\.com", re.IGNORECASE)
LOCAL_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|\\\\wsl|/mnt/|/home/)", re.IGNORECASE)
SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|secret|password|access[_-]?token|refresh[_-]?token|cookie|openid|unionid|fakeid)\s*[:=]",
    re.IGNORECASE,
)


def now_stamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return f"<external_path_hash:{hashlib.sha256(str(path).encode('utf-8')).hexdigest()[:16]}>"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


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


def fetch_search_docs(conn: sqlite3.Connection, event_ids: list[str]) -> dict[str, dict[str, Any]]:
    docs: dict[str, dict[str, Any]] = {}
    for batch in chunked(event_ids):
        placeholders = ",".join("?" for _ in batch)
        for row in conn.execute(
            f"""
            SELECT doc_rowid, subject_id, subject_type, city_text, search_text
            FROM search_document
            WHERE subject_type = 'event' AND subject_id IN ({placeholders})
            """,
            batch,
        ):
            docs[str(row["subject_id"])] = {
                "doc_rowid": int(row["doc_rowid"]),
                "subject_id": str(row["subject_id"]),
                "city_text": row["city_text"] or "",
                "search_text": row["search_text"] or "",
            }
    return docs


def validate_search_docs(
    overlay_rows: list[dict[str, Any]],
    docs: dict[str, dict[str, Any]],
    sample_limit: int,
) -> tuple[dict[str, int], list[dict[str, Any]], list[dict[str, Any]]]:
    counts = Counter()
    samples: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for row in overlay_rows:
        event_id = str(row.get("event_id") or "")
        city = str(row.get("proposed_city") or "").strip()
        doc = docs.get(event_id)
        if not doc:
            counts["direct_search_missing_rows"] += 1
            failed.append({"event_id": event_id, "proposed_city": city, "reason": "missing_event_search_document"})
            continue
        city_match = doc["city_text"].strip() == city
        search_text_has_city = city in doc["search_text"]
        if city_match and search_text_has_city:
            counts["direct_search_city_match_rows"] += 1
        else:
            if not city_match:
                counts["direct_search_city_mismatch_rows"] += 1
            if not search_text_has_city:
                counts["direct_search_text_missing_city_rows"] += 1
            failed.append(
                {
                    "event_id": event_id,
                    "doc_rowid": doc["doc_rowid"],
                    "proposed_city": city,
                    "city_text_hash": stable_hash(doc["city_text"]),
                    "reason": "event_search_document_city_or_text_mismatch",
                }
            )
        if len(samples) < sample_limit:
            samples.append(
                {
                    "event_id": event_id,
                    "doc_rowid": doc["doc_rowid"],
                    "proposed_city": city,
                    "city_text_matches": city_match,
                    "search_text_has_city": search_text_has_city,
                    "sample_hash": stable_hash(
                        {
                            "event_id": event_id,
                            "doc_rowid": doc["doc_rowid"],
                            "proposed_city": city,
                            "city_text_matches": city_match,
                            "search_text_has_city": search_text_has_city,
                        }
                    ),
                }
            )
    counts["direct_search_checked_rows"] = len(overlay_rows)
    return dict(counts), samples, failed


def graph_smoke(
    conn: sqlite3.Connection,
    overlay_rows: list[dict[str, Any]],
    sample_limit: int,
) -> tuple[dict[str, int], list[dict[str, Any]], list[dict[str, Any]]]:
    event_city = {str(row.get("event_id")): str(row.get("proposed_city") or "").strip() for row in overlay_rows}
    event_ids = list(event_city.keys())
    event_edges: dict[str, list[dict[str, str]]] = defaultdict(list)
    for batch in chunked(event_ids):
        placeholders = ",".join("?" for _ in batch)
        for row in conn.execute(
            f"SELECT event_id, dj_id, city FROM dj_event WHERE event_id IN ({placeholders})",
            batch,
        ):
            event_edges[str(row["event_id"])].append(
                {
                    "dj_id": str(row["dj_id"]),
                    "city": row["city"] or "",
                }
            )

    all_djs = sorted({edge["dj_id"] for edges in event_edges.values() for edge in edges})
    graph_seed_rows: set[str] = set()
    if all_djs and table_exists(conn, "graph_window_cache"):
        for batch in chunked(all_djs):
            placeholders = ",".join("?" for _ in batch)
            for row in conn.execute(
                f"SELECT seed_subject_id FROM graph_window_cache WHERE seed_subject_id IN ({placeholders})",
                batch,
            ):
                graph_seed_rows.add(str(row["seed_subject_id"]))

    counts = Counter()
    samples: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for event_id, city in event_city.items():
        edges = event_edges.get(event_id, [])
        if not edges:
            counts["graph_event_edge_missing_rows"] += 1
            failed.append({"event_id": event_id, "proposed_city": city, "reason": "missing_dj_event_edges"})
            continue
        city_match_edges = [edge for edge in edges if edge["city"].strip() == city]
        if not city_match_edges:
            counts["graph_event_city_edge_missing_rows"] += 1
            failed.append({"event_id": event_id, "proposed_city": city, "reason": "missing_city_matched_dj_event_edges"})
        if len(samples) < sample_limit:
            event_djs = sorted({edge["dj_id"] for edge in edges})
            missing_seed_djs = [dj_id for dj_id in event_djs if dj_id not in graph_seed_rows]
            samples.append(
                {
                    "event_id": event_id,
                    "proposed_city": city,
                    "dj_event_edge_count": len(edges),
                    "city_matched_edge_count": len(city_match_edges),
                    "graph_window_seed_count": len(event_djs) - len(missing_seed_djs),
                    "graph_window_missing_seed_count": len(missing_seed_djs),
                    "sample_hash": stable_hash(
                        {
                            "event_id": event_id,
                            "proposed_city": city,
                            "dj_ids": event_djs,
                            "missing_seed_djs": missing_seed_djs,
                        }
                    ),
                }
            )

    djs_with_edges = {edge["dj_id"] for edges in event_edges.values() for edge in edges}
    missing_graph_seeds = djs_with_edges - graph_seed_rows
    counts.update(
        {
            "graph_event_rows_checked": len(event_city),
            "graph_dj_event_edges": sum(len(edges) for edges in event_edges.values()),
            "graph_unique_dj_ids": len(djs_with_edges),
            "graph_window_seed_rows": len(graph_seed_rows),
            "graph_window_missing_seed_rows": len(missing_graph_seeds),
        }
    )
    if missing_graph_seeds:
        for dj_id in sorted(missing_graph_seeds)[:sample_limit]:
            failed.append({"dj_id": dj_id, "reason": "missing_graph_window_seed"})
    return dict(counts), samples, failed


def fts_status(conn: sqlite3.Connection, overlay_rows: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    city_counts = Counter(str(row.get("proposed_city") or "").strip() for row in overlay_rows)
    city_counts.pop("", None)
    term_rows: list[dict[str, Any]] = []
    terms_with_hits = 0
    errors: list[str] = []
    for city, expected_rows in sorted(city_counts.items()):
        hit_count = 0
        try:
            if table_exists(conn, "search_document_fts"):
                hit_count = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM search_document_fts WHERE search_document_fts MATCH ?",
                        (city,),
                    ).fetchone()[0]
                )
        except sqlite3.Error as exc:
            errors.append(f"{city}:{exc.__class__.__name__}")
        if hit_count:
            terms_with_hits += 1
        term_rows.append(
            {
                "city": city,
                "overlay_search_document_rows": int(expected_rows),
                "fts_match_rows": int(hit_count),
                "fts_refresh_required": hit_count < expected_rows,
            }
        )
    expected_refresh = int(summary.get("counts", {}).get("search_document_fts_refresh_required_rows", len(overlay_rows)))
    return {
        "city_terms_checked": len(term_rows),
        "city_terms_with_fts_hits": terms_with_hits,
        "city_terms_requiring_refresh": sum(1 for row in term_rows if row["fts_refresh_required"]),
        "fts_refresh_required_rows": expected_refresh,
        "fts_errors": errors,
        "term_rows": term_rows,
    }


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


def leak_scan(value: Any) -> dict[str, int]:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return {
        "public_url_hits": len(PUBLIC_URL_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
        "sensitive_key_hits": len(SENSITIVE_KEY_RE.findall(text)),
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    counts = report["counts"]
    fts = report["fts_status"]
    boundary = report["boundary_truth"]
    lines = [
        "# Atlas T5 Serving City Overlay Search/Graph Smoke",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Decision",
        "",
        f"`{report['decision']}`",
        "",
        f"Failed checks: `{report['failed_checks']}`",
        "",
        "This is report-local/read-only evidence for the city overlay candidate. It does not mutate the selected serving SQLite, source/raw SQLite, graph/vector stores, public pointers, huaidj.club, CloudRun/VPS, mini-program state, or memory.",
        "",
        "## Counts",
        "",
        f"- overlay search rows checked: `{counts['overlay_search_document_rows_input']}`",
        f"- direct search city matches: `{counts['direct_search_city_match_rows']}`",
        f"- direct search missing/mismatch/text-missing rows: `{counts['direct_search_missing_rows']}` / `{counts['direct_search_city_mismatch_rows']}` / `{counts['direct_search_text_missing_city_rows']}`",
        f"- graph event rows / DJ-event edges / unique DJs: `{counts['graph_event_rows_checked']}` / `{counts['graph_dj_event_edges']}` / `{counts['graph_unique_dj_ids']}`",
        f"- graph window seeds / missing seeds: `{counts['graph_window_seed_rows']}` / `{counts['graph_window_missing_seed_rows']}`",
        f"- table/field metric drift rows: `{counts['metric_drift_rows']}`",
        f"- FTS refresh required rows: `{fts['fts_refresh_required_rows']}`",
        f"- FTS city terms requiring refresh: `{fts['city_terms_requiring_refresh']}`",
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
    overlay_summary: Path,
    overlay_search_rows: Path,
    candidate_db: Path | None,
    out_dir: Path,
    report_path: Path,
    sample_limit: int = 200,
) -> dict[str, Any]:
    summary = read_json(overlay_summary)
    overlay_rows = read_jsonl(overlay_search_rows)
    resolved_candidate = candidate_db or (REPO_ROOT / summary["outputs"]["candidate_db"])
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = connect_readonly(resolved_candidate)
    try:
        event_ids = [str(row.get("event_id")) for row in overlay_rows if row.get("event_id")]
        docs = fetch_search_docs(conn, event_ids)
        search_counts, search_samples, search_failures = validate_search_docs(overlay_rows, docs, sample_limit)
        graph_counts, graph_samples, graph_failures = graph_smoke(conn, overlay_rows, sample_limit)
        fts = fts_status(conn, overlay_rows, summary)
        metrics, metric_drift = metric_readback(conn, summary)
    finally:
        conn.close()

    failed_checks: list[str] = []
    if search_failures:
        failed_checks.append("direct_search_document_city_readback_failed")
    if graph_counts.get("graph_event_edge_missing_rows", 0) or graph_counts.get("graph_event_city_edge_missing_rows", 0):
        failed_checks.append("graph_dj_event_city_readback_failed")
    if graph_counts.get("graph_window_missing_seed_rows", 0):
        failed_checks.append("graph_window_seed_missing")
    if metric_drift:
        failed_checks.append("candidate_metric_drift")
    if fts["fts_errors"]:
        failed_checks.append("fts_query_errors")

    counts = {
        "overlay_search_document_rows_input": len(overlay_rows),
        "candidate_db_opened_read_only": 1,
        "direct_search_checked_rows": search_counts.get("direct_search_checked_rows", 0),
        "direct_search_city_match_rows": search_counts.get("direct_search_city_match_rows", 0),
        "direct_search_missing_rows": search_counts.get("direct_search_missing_rows", 0),
        "direct_search_city_mismatch_rows": search_counts.get("direct_search_city_mismatch_rows", 0),
        "direct_search_text_missing_city_rows": search_counts.get("direct_search_text_missing_city_rows", 0),
        "graph_event_rows_checked": graph_counts.get("graph_event_rows_checked", 0),
        "graph_event_edge_missing_rows": graph_counts.get("graph_event_edge_missing_rows", 0),
        "graph_event_city_edge_missing_rows": graph_counts.get("graph_event_city_edge_missing_rows", 0),
        "graph_dj_event_edges": graph_counts.get("graph_dj_event_edges", 0),
        "graph_unique_dj_ids": graph_counts.get("graph_unique_dj_ids", 0),
        "graph_window_seed_rows": graph_counts.get("graph_window_seed_rows", 0),
        "graph_window_missing_seed_rows": graph_counts.get("graph_window_missing_seed_rows", 0),
        "metric_drift_rows": len(metric_drift),
        "source_sqlite_write_rows": 0,
        "serving_rebuild_rows": 0,
        "graph_write_rows": 0,
        "public_serving_field_rows": 0,
        "memory_write_rows": 0,
    }

    decision = (
        "atlas_t5_serving_city_overlay_search_graph_smoke_blocked_report_only"
        if failed_checks
        else "atlas_t5_serving_city_overlay_search_graph_smoke_ready_fts_refresh_required_report_only"
        if fts["fts_refresh_required_rows"]
        else "atlas_t5_serving_city_overlay_search_graph_smoke_ready_report_only"
    )

    outputs = {
        "summary_json": rel(out_dir / "serving_city_overlay_search_graph_smoke_summary.json"),
        "direct_search_samples": rel(out_dir / "serving_city_overlay_direct_search_samples.jsonl"),
        "graph_samples": rel(out_dir / "serving_city_overlay_graph_samples.jsonl"),
        "failed_rows": rel(out_dir / "serving_city_overlay_smoke_failed_rows.jsonl"),
        "fts_status": rel(out_dir / "serving_city_overlay_fts_status.json"),
        "api_contract": rel(out_dir / "serving_city_overlay_api_contract.json"),
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
        "schema_version": "stage7_atlas_t5_serving_city_overlay_api_contract.v1",
        "candidate_db": rel(resolved_candidate),
        "routes": {
            "event_city_detail": {"source": outputs["direct_search_samples"], "status": "ready_report_only"},
            "event_graph_neighbors": {"source": outputs["graph_samples"], "status": "ready_report_only"},
            "city_search_direct": {"mode": "search_document_like_or_api_query", "status": "ready_report_only"},
            "city_search_fts": {"mode": "search_document_fts", "status": "refresh_required_before_public"},
        },
        "public_serving_approved": False,
    }
    report = {
        "schema_version": "stage7_atlas_t5_serving_city_overlay_search_graph_smoke.v1.summary",
        "generated_at": now_stamp(),
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {
            "overlay_summary": rel(overlay_summary),
            "overlay_search_rows": rel(overlay_search_rows),
            "candidate_db": rel(resolved_candidate),
        },
        "counts": counts,
        "metrics_readback": metrics,
        "metric_drift_rows": metric_drift,
        "fts_status": {key: value for key, value in fts.items() if key != "term_rows"},
        "leak_scan": {"public_url_hits": 0, "local_path_hits": 0, "sensitive_key_hits": 0},
        "boundary_truth": boundary_truth,
        "outputs": outputs,
        "next_resume_pointer": (
            "tools\\stage7_rewrite\\reports\\atlas_t5_serving_city_overlay_search_graph_smoke_20260527\\"
            "serving_city_overlay_search_graph_smoke_summary.json. "
            "Next: build a bounded FTS delta/rebuild gate for the 12284 deferred event search rows before any public serving promotion; "
            "if FTS refresh blocks, pivot to time_title_recovery_work_orders.jsonl or source_ocr_gap_recovery_work_orders.jsonl."
        ),
    }
    combined_for_scan = {
        "report": report,
        "api_contract": api_contract,
        "search_samples": search_samples,
        "graph_samples": graph_samples,
        "failed_rows": search_failures + graph_failures + metric_drift,
        "fts_status_rows": fts["term_rows"],
    }
    report["leak_scan"] = leak_scan(combined_for_scan)
    if any(report["leak_scan"].values()) and "leak_scan_hits_present" not in failed_checks:
        report["failed_checks"].append("leak_scan_hits_present")
        report["decision"] = "atlas_t5_serving_city_overlay_search_graph_smoke_blocked_report_only"

    write_jsonl(out_dir / "serving_city_overlay_direct_search_samples.jsonl", search_samples)
    write_jsonl(out_dir / "serving_city_overlay_graph_samples.jsonl", graph_samples)
    write_jsonl(out_dir / "serving_city_overlay_smoke_failed_rows.jsonl", search_failures + graph_failures + metric_drift)
    write_json(out_dir / "serving_city_overlay_fts_status.json", fts)
    write_json(out_dir / "serving_city_overlay_api_contract.json", api_contract)
    write_json(out_dir / "serving_city_overlay_search_graph_smoke_summary.json", report)
    write_report(report_path, report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overlay-summary", type=Path, default=DEFAULT_OVERLAY_SUMMARY)
    parser.add_argument("--overlay-search-rows", type=Path, default=DEFAULT_OVERLAY_SEARCH_ROWS)
    parser.add_argument("--candidate-db", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--sample-limit", type=int, default=200)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_smoke(
        overlay_summary=args.overlay_summary,
        overlay_search_rows=args.overlay_search_rows,
        candidate_db=args.candidate_db,
        out_dir=args.out_dir,
        report_path=args.report_path,
        sample_limit=args.sample_limit,
    )
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "failed_checks": report["failed_checks"],
                "summary_json": report["outputs"]["summary_json"],
                "report": report["outputs"]["report"],
                "direct_search_city_match_rows": report["counts"]["direct_search_city_match_rows"],
                "graph_dj_event_edges": report["counts"]["graph_dj_event_edges"],
                "fts_refresh_required_rows": report["fts_status"]["fts_refresh_required_rows"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
