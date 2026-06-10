#!/usr/bin/env python3
"""Build a report-local search-date refresh candidate for the time overlay.

The prior smoke proved that the report-local time overlay has correct
`starts_at` readback and graph coverage, but event search text still needs a
bounded date refresh before public packaging. This script copies the candidate
serving DB, updates only event search_document rows touched by the time overlay,
rebuilds FTS in the copied DB, and writes rollback/readback evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SMOKE_SUMMARY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t5_serving_time_overlay_search_graph_smoke_20260527"
    / "serving_time_overlay_search_graph_smoke_summary.json"
)
DEFAULT_CHANGED_ROWS = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t5_serving_time_overlay_candidate_20260527"
    / "serving_time_overlay_changed_rows.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t5_serving_time_overlay_search_date_refresh_gate_20260527"
DEFAULT_CANDIDATE_DB = REPO_ROOT / "reports" / "atlas_serving_time_overlay_search_date_refresh_candidate_20260527_1518" / "atlas_serving.sqlite"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "ATLAS_T5_SERVING_TIME_OVERLAY_SEARCH_DATE_REFRESH_GATE_20260527.md"
EXPECTED_SMOKE_DECISION = "atlas_t5_serving_time_overlay_search_graph_smoke_ready_search_date_refresh_required_report_only"
SCHEMA_VERSION = "stage7_atlas_t5_serving_time_overlay_search_date_refresh_gate.v1"
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


def row_hash(row: sqlite3.Row) -> str:
    return stable_hash({key: row[key] for key in row.keys()})


def chunked(values: list[str], size: int = 500) -> Iterable[list[str]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def connect(path: Path, *, readonly: bool) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ? AND type IN ('table', 'view')",
        (table,),
    ).fetchone()
    return bool(row)


def require_columns(conn: sqlite3.Connection, table: str, required: set[str]) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    missing = sorted(required - columns)
    if missing:
        raise RuntimeError(f"{table} missing required columns: {missing}")


def table_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def date_tokens(date_value: str) -> list[str]:
    date_value = str(date_value or "").strip()
    parts = date_value.split("-")
    if len(parts) != 3:
        return [date_value] if date_value else []
    year, month, day = parts
    month_i = int(month)
    day_i = int(day)
    return [
        date_value,
        f"{month_i}月{day_i}日",
        f"{year}/{month_i}/{day_i}",
        f"{month_i}/{day_i}",
        f"{month_i}.{day_i:02d}",
        f"{month_i}.{day_i}",
    ]


def append_date_tokens(search_text: str, date_value: str) -> tuple[str, list[str]]:
    existing = str(search_text or "")
    appended: list[str] = []
    for token in date_tokens(date_value)[:2]:
        if token and token not in existing:
            appended.append(token)
    if not appended:
        return existing, []
    return (existing.rstrip() + " " + " ".join(appended)).strip(), appended


def has_any_date_token(search_text: str, date_value: str) -> bool:
    text = str(search_text or "")
    return any(token and token in text for token in date_tokens(date_value))


def fts_match(conn: sqlite3.Connection, doc_rowid: int, date_value: str) -> bool:
    queries: list[str] = []
    tokens = date_tokens(date_value)
    if tokens:
        queries.append(f'"{tokens[0]}"')
    if len(tokens) > 1:
        queries.append(f'"{tokens[1]}"')
    for query in queries:
        try:
            row = conn.execute(
                "SELECT 1 FROM search_document_fts WHERE rowid = ? AND search_document_fts MATCH ? LIMIT 1",
                (doc_rowid, query),
            ).fetchone()
        except sqlite3.Error:
            row = None
        if row:
            return True
    return False


def scan_leaks(paths: list[Path]) -> dict[str, int]:
    raw_url_hits = 0
    local_path_hits = 0
    sensitive_key_hits = 0
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        raw_url_hits += len(PUBLIC_URL_RE.findall(text))
        local_path_hits += len(LOCAL_PATH_RE.findall(text))
        sensitive_key_hits += len(SENSITIVE_KEY_RE.findall(text))
    return {
        "leak_raw_url_hits": raw_url_hits,
        "leak_local_path_hits": local_path_hits,
        "sensitive_key_hits": sensitive_key_hits,
    }


def performance_targets(changed_rows: list[dict[str, Any]]) -> dict[str, str]:
    targets: dict[str, str] = {}
    for row in changed_rows:
        if row.get("target_table") != "performance_event":
            continue
        event_id = str(row.get("event_id") or "").strip()
        starts_at = str(row.get("proposed_starts_at") or "").strip()
        if event_id and starts_at:
            previous = targets.setdefault(event_id, starts_at)
            if previous != starts_at:
                raise RuntimeError(f"conflicting proposed_starts_at for {event_id}: {previous} vs {starts_at}")
    return targets


def load_docs(conn: sqlite3.Connection, event_ids: list[str]) -> dict[str, sqlite3.Row]:
    docs: dict[str, sqlite3.Row] = {}
    for batch in chunked(sorted(event_ids)):
        placeholders = ",".join("?" for _ in batch)
        for row in conn.execute(
            f"""
            SELECT doc_rowid, subject_id, subject_type, display_name, normalized_name,
                   aliases_text, city_text, taxon_path, rank_score, last_seen_at,
                   public_state, search_text
            FROM search_document
            WHERE subject_type = 'event' AND subject_id IN ({placeholders})
            """,
            batch,
        ):
            docs[str(row["subject_id"])] = row
    return docs


def copy_candidate_db(source_db: Path, target_db: Path, *, allow_external_target: bool = False) -> None:
    source_resolved = source_db.resolve()
    target_resolved = target_db.resolve()
    reports_root = (REPO_ROOT / "reports").resolve()
    if not allow_external_target and reports_root not in target_resolved.parents:
        raise RuntimeError(f"target candidate DB must stay under reports: {target_db}")
    if not source_resolved.exists():
        raise FileNotFoundError(source_db)
    target_resolved.parent.mkdir(parents=True, exist_ok=True)
    if target_resolved.exists():
        target_resolved.unlink()
    shutil.copy2(source_resolved, target_resolved)


def metrics(conn: sqlite3.Connection) -> dict[str, Any]:
    tables = ["performance_event", "dj_event", "search_document", "search_document_fts", "graph_window_cache"]
    return {"table_counts": {table: table_count(conn, table) for table in tables if table_exists(conn, table)}}


def build_gate(
    smoke_summary_path: Path = DEFAULT_SMOKE_SUMMARY,
    changed_rows_path: Path = DEFAULT_CHANGED_ROWS,
    candidate_db: Path | None = None,
    out_candidate_db: Path = DEFAULT_CANDIDATE_DB,
    out_dir: Path = DEFAULT_OUT_DIR,
    report_path: Path = DEFAULT_REPORT_PATH,
    sample_limit: int = 50,
    allow_external_candidate_db: bool = False,
) -> dict[str, Any]:
    smoke_summary = read_json(smoke_summary_path)
    if smoke_summary.get("decision") != EXPECTED_SMOKE_DECISION:
        raise RuntimeError(f"unexpected smoke decision: {smoke_summary.get('decision')}")
    source_db = candidate_db or (REPO_ROOT / smoke_summary["inputs"]["candidate_db"])
    changed_rows = read_jsonl(changed_rows_path)
    targets = performance_targets(changed_rows)

    out_dir.mkdir(parents=True, exist_ok=True)
    copy_candidate_db(source_db, out_candidate_db, allow_external_target=allow_external_candidate_db)

    rollback_rows: list[dict[str, Any]] = []
    refreshed_rows: list[dict[str, Any]] = []
    readback_rows: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()

    with connect(out_candidate_db, readonly=False) as conn:
        require_columns(conn, "search_document", {"doc_rowid", "subject_id", "subject_type", "search_text"})
        require_columns(conn, "performance_event", {"event_id", "starts_at"})
        if not table_exists(conn, "search_document_fts"):
            raise RuntimeError("search_document_fts table missing")
        before_metrics = metrics(conn)
        docs = load_docs(conn, list(targets))
        counts["input_changed_rows"] = len(changed_rows)
        counts["performance_event_refresh_target_rows"] = len(targets)
        counts["search_date_refresh_required_rows"] = int(
            smoke_summary.get("counts", {}).get("search_date_refresh_required_rows", 0)
        )

        for event_id, proposed_date in sorted(targets.items()):
            doc = docs.get(event_id)
            if doc is None:
                blocked_rows.append({"event_id": event_id, "reason": "event_search_document_missing"})
                continue
            old_text = str(doc["search_text"] or "")
            new_text, appended = append_date_tokens(old_text, proposed_date)
            pre_hash = row_hash(doc)
            rollback_rows.append(
                {
                    "schema_version": SCHEMA_VERSION + ".rollback_row",
                    "doc_rowid": int(doc["doc_rowid"]),
                    "event_id": event_id,
                    "prewrite_hash": pre_hash,
                    "rollback_search_text_hash": stable_hash(old_text),
                }
            )
            conn.execute(
                "UPDATE search_document SET search_text = ? WHERE doc_rowid = ?",
                (new_text, int(doc["doc_rowid"])),
            )
            refreshed_rows.append(
                {
                    "schema_version": SCHEMA_VERSION + ".refreshed_row",
                    "doc_rowid": int(doc["doc_rowid"]),
                    "event_id": event_id,
                    "proposed_starts_at": proposed_date,
                    "appended_date_tokens": appended,
                    "search_text_changed": new_text != old_text,
                    "prewrite_hash": pre_hash,
                    "postwrite_search_text_hash": stable_hash(new_text),
                }
            )
            if len(samples) < sample_limit:
                samples.append(
                    {
                        "doc_rowid": int(doc["doc_rowid"]),
                        "event_id": event_id,
                        "proposed_starts_at": proposed_date,
                        "search_text_changed": new_text != old_text,
                        "appended_date_tokens": appended,
                        "display_name_hash": stable_hash(doc["display_name"] or ""),
                    }
                )

        conn.execute("INSERT INTO search_document_fts(search_document_fts) VALUES('rebuild')")
        conn.commit()

        post_docs = load_docs(conn, list(targets))
        for event_id, proposed_date in sorted(targets.items()):
            doc = post_docs.get(event_id)
            if doc is None:
                continue
            text_has_date = has_any_date_token(str(doc["search_text"] or ""), proposed_date)
            fts_has_date = fts_match(conn, int(doc["doc_rowid"]), proposed_date)
            readback_rows.append(
                {
                    "schema_version": SCHEMA_VERSION + ".postwrite_readback",
                    "doc_rowid": int(doc["doc_rowid"]),
                    "event_id": event_id,
                    "proposed_starts_at": proposed_date,
                    "search_text_has_date": text_has_date,
                    "fts_has_date": fts_has_date,
                    "postwrite_hash": row_hash(doc),
                }
            )
            counts["postwrite_search_text_date_match_rows"] += int(text_has_date)
            counts["postwrite_fts_date_match_rows"] += int(fts_has_date)
        after_metrics = metrics(conn)

    counts["search_document_rows"] = len(docs)
    counts["search_document_missing_rows"] = len(blocked_rows)
    counts["search_document_update_rows"] = len(refreshed_rows)
    counts["search_text_changed_rows"] = sum(1 for row in refreshed_rows if row["search_text_changed"])
    counts["rollback_contract_rows"] = len(rollback_rows)
    counts["postwrite_readback_rows"] = len(readback_rows)
    counts["table_count_drift_rows"] = sum(
        1
        for table, before in before_metrics["table_counts"].items()
        if after_metrics["table_counts"].get(table) != before
    )

    outputs = {
        "blocked_rows": out_dir / "serving_time_overlay_search_date_refresh_blocked_rows.jsonl",
        "candidate_db": out_candidate_db,
        "postwrite_readback_rows": out_dir / "serving_time_overlay_search_date_refresh_postwrite_readback_rows.jsonl",
        "refreshed_rows": out_dir / "serving_time_overlay_search_date_refresh_rows.jsonl",
        "rollback_contracts": out_dir / "serving_time_overlay_search_date_refresh_rollback_contracts.jsonl",
        "samples": out_dir / "serving_time_overlay_search_date_refresh_samples.jsonl",
        "summary_json": out_dir / "serving_time_overlay_search_date_refresh_summary.json",
        "report": report_path,
    }
    write_jsonl(outputs["blocked_rows"], blocked_rows)
    write_jsonl(outputs["refreshed_rows"], refreshed_rows)
    write_jsonl(outputs["rollback_contracts"], rollback_rows)
    write_jsonl(outputs["postwrite_readback_rows"], readback_rows)
    write_jsonl(outputs["samples"], samples)

    failed_checks: list[str] = []
    if blocked_rows:
        failed_checks.append("search_document_missing_rows_present")
    if counts["postwrite_search_text_date_match_rows"] != counts["performance_event_refresh_target_rows"]:
        failed_checks.append("postwrite_search_text_date_readback_failed")
    if counts["postwrite_fts_date_match_rows"] != counts["performance_event_refresh_target_rows"]:
        failed_checks.append("postwrite_fts_date_readback_failed")
    if counts["table_count_drift_rows"]:
        failed_checks.append("table_count_drift_detected")

    leak_paths = [outputs["blocked_rows"], outputs["refreshed_rows"], outputs["rollback_contracts"], outputs["postwrite_readback_rows"], outputs["samples"]]
    leaks = scan_leaks(leak_paths)
    if leaks["leak_raw_url_hits"]:
        failed_checks.append("raw_url_leak_hits_present")
    if leaks["leak_local_path_hits"]:
        failed_checks.append("local_path_leak_hits_present")
    if leaks["sensitive_key_hits"]:
        failed_checks.append("sensitive_key_hits_present")

    decision = (
        "atlas_t5_serving_time_overlay_search_date_refresh_blocked_report_local"
        if failed_checks
        else "atlas_t5_serving_time_overlay_search_date_refresh_candidate_ready_report_local"
    )
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": now_iso(),
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {
            "smoke_summary": rel(smoke_summary_path),
            "changed_rows": rel(changed_rows_path),
            "source_candidate_db": rel(source_db),
        },
        "outputs": {key: rel(value) for key, value in outputs.items()},
        "counts": {key: int(value) for key, value in sorted(counts.items())},
        "metrics": {"before": before_metrics, "after": after_metrics},
        "boundary_truth": {
            "cloudrun_or_vps_deploy_executed": False,
            "graph_vector_public_mutation_executed": False,
            "huaidj_club_upload_executed": False,
            "mini_program_upload_or_review_executed": False,
            "network_ocr_model_memory_executed": False,
            "public_pointer_updated": False,
            "report_local_candidate_db_mutated": True,
            "selected_serving_db_mutated": False,
            "source_raw_db_opened": False,
            "source_raw_db_write_executed": False,
        },
        "leak_raw_url_hits": leaks["leak_raw_url_hits"],
        "leak_local_path_hits": leaks["leak_local_path_hits"],
        "sensitive_key_hits": leaks["sensitive_key_hits"],
        "next_resume_pointer": (
            f"{rel(outputs['summary_json'])}. Next: run local API/browser/search smoke against the refreshed report-local candidate; "
            "public upload remains disabled unless explicitly re-enabled."
        ),
    }
    write_json(outputs["summary_json"], summary)
    render_report(report_path, summary)
    return summary


def render_report(path: Path, summary: dict[str, Any]) -> None:
    c = summary["counts"]
    def count(name: str) -> int:
        return int(c.get(name, 0))

    lines = [
        "# ATLAS T5 Serving Time Overlay Search-Date Refresh Gate - 2026-05-27",
        "",
        "## Decision",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Input changed rows: `{count('input_changed_rows')}`",
        f"- Event search refresh target rows: `{count('performance_event_refresh_target_rows')}`",
        f"- Search document rows/missing: `{count('search_document_rows')}` / `{count('search_document_missing_rows')}`",
        f"- Search document update rows/text-changed rows: `{count('search_document_update_rows')}` / `{count('search_text_changed_rows')}`",
        f"- Postwrite search text date matches: `{count('postwrite_search_text_date_match_rows')}`",
        f"- Postwrite FTS date matches: `{count('postwrite_fts_date_match_rows')}`",
        f"- Rollback/postwrite contracts: `{count('rollback_contract_rows')}` / `{count('postwrite_readback_rows')}`",
        f"- Table-count drift rows: `{count('table_count_drift_rows')}`",
        f"- Leak hits raw-url/local-path/sensitive-key: `{summary['leak_raw_url_hits']}` / `{summary['leak_local_path_hits']}` / `{summary['sensitive_key_hits']}`",
        "",
        "## LLM Audit",
        "",
        "- The previous smoke proved starts_at and graph-window correctness but separated search-date readiness. This gate updates only report-local event search documents, appends deterministic date tokens, rebuilds FTS in the copied candidate DB, and records rollback/readback contracts before any public packaging.",
        "",
        "## Boundary Truth",
        "",
        "- Report-local candidate DB mutation only.",
        "- No source/raw DB open or write.",
        "- No selected serving SQLite mutation.",
        "- No graph/vector/public pointer mutation, huaidj.club upload, CloudRun/VPS deploy, mini-program upload/review, memory write, network/OCR/model call, credential read, 9router, destructive Git, or D-root scan.",
        "",
        "## Evidence",
        "",
        f"- Summary JSON: `{summary['outputs']['summary_json']}`",
        f"- Candidate DB: `{summary['outputs']['candidate_db']}`",
        f"- Refreshed rows: `{summary['outputs']['refreshed_rows']}`",
        f"- Rollback contracts: `{summary['outputs']['rollback_contracts']}`",
        f"- Postwrite readback rows: `{summary['outputs']['postwrite_readback_rows']}`",
        "",
        "## Next Resume Pointer",
        "",
        f"`{summary['next_resume_pointer']}`",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-summary", type=Path, default=DEFAULT_SMOKE_SUMMARY)
    parser.add_argument("--changed-rows", type=Path, default=DEFAULT_CHANGED_ROWS)
    parser.add_argument("--candidate-db", type=Path, default=None)
    parser.add_argument("--out-candidate-db", type=Path, default=DEFAULT_CANDIDATE_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--sample-limit", type=int, default=50)
    parser.add_argument("--allow-external-candidate-db", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_gate(
        smoke_summary_path=args.smoke_summary,
        changed_rows_path=args.changed_rows,
        candidate_db=args.candidate_db,
        out_candidate_db=args.out_candidate_db,
        out_dir=args.out_dir,
        report_path=args.report_path,
        sample_limit=args.sample_limit,
        allow_external_candidate_db=args.allow_external_candidate_db,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "failed_checks": summary["failed_checks"],
                "search_document_update_rows": summary["counts"]["search_document_update_rows"],
                "postwrite_fts_date_match_rows": summary["counts"]["postwrite_fts_date_match_rows"],
                "summary_json": summary["outputs"]["summary_json"],
                "report": summary["outputs"]["report"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if not summary["failed_checks"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
