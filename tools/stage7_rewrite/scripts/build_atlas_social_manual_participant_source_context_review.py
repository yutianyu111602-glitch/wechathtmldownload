#!/usr/bin/env python3
"""Build a report-only source-context review packet for Q6 manual participant rows."""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_WORK_ORDERS = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_review_triage_q6_20260526"
    / "manual_participant_review_work_orders.jsonl"
)
DEFAULT_BATCHES = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_review_triage_q6_20260526"
    / "source_account_batch_queue.jsonl"
)
DEFAULT_SERVING_DB = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "atlas_serving.sqlite"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_source_context_review_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_SOURCE_CONTEXT_REVIEW_20260526.md"
DEFAULT_SOURCE_ACCOUNTS = ["Dada Kunming", "Dada Bar Beijing", "OIL油", "TRUST 相信电音"]
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_source_context_review.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for manual participant source-context review: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def normalize(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", compact(value, 1000).casefold())


def number(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no}: expected object row")
            rows.append(row)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def connect_serving_db(path: Path) -> sqlite3.Connection:
    reject_d_path(path, "serving_db")
    if not path.exists():
        raise FileNotFoundError(path)
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


def rowdict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def choose_source_accounts(batch_rows: list[dict[str, Any]], requested: list[str], top_batches: int) -> list[str]:
    if requested:
        return [compact(value, 220) for value in requested if compact(value, 220)]
    top = [compact(row.get("source_account"), 220) for row in batch_rows[:top_batches]]
    return [value for value in top if value]


def title_match(source_title: str, target_title: str) -> tuple[float, str]:
    source = compact(source_title, 500)
    target = compact(target_title, 500)
    if source and source == target:
        return 1.0, "exact_title"
    source_norm = normalize(source)
    target_norm = normalize(target)
    if not source_norm or not target_norm:
        return 0.0, "no_title"
    if source_norm == target_norm:
        return 0.98, "normalized_exact_title"
    shorter = min(len(source_norm), len(target_norm))
    if shorter >= 10 and (source_norm in target_norm or target_norm in source_norm):
        return 0.94, "normalized_contains_title"
    ratio = difflib.SequenceMatcher(None, source_norm, target_norm).ratio()
    if ratio >= 0.9 and source_norm[:8] == target_norm[:8]:
        return ratio, "normalized_high_ratio_title"
    return ratio, "weak_title_match"


def event_match(event_title: str, candidate_name: str) -> tuple[float, str]:
    event_norm = normalize(event_title)
    name_norm = normalize(candidate_name)
    if not event_norm or not name_norm:
        return 0.0, "no_event_name"
    if event_norm == name_norm:
        return 1.0, "exact_event_name"
    shorter = min(len(event_norm), len(name_norm))
    if shorter >= 6 and (event_norm in name_norm or name_norm in event_norm):
        return 0.9, "normalized_contains_event_name"
    return difflib.SequenceMatcher(None, event_norm, name_norm).ratio(), "event_name_similarity"


def load_account_evidence(conn: sqlite3.Connection, source_accounts: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not table_exists(conn, "evidence_ref"):
        return {account: [] for account in source_accounts}
    by_account: dict[str, list[dict[str, Any]]] = {}
    for account in source_accounts:
        rows = conn.execute(
            """
            SELECT source_ref_id, source_hash, source_account, source_title, post_date, public_url_allowed
            FROM evidence_ref
            WHERE source_account = ?
            ORDER BY post_date DESC, source_title
            """,
            (account,),
        ).fetchall()
        by_account[account] = [rowdict(row) for row in rows]
    return by_account


def best_source_matches(row: dict[str, Any], account_evidence: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    title = compact(row.get("title"), 500)
    matches: list[dict[str, Any]] = []
    for evidence in account_evidence:
        score, strategy = title_match(compact(evidence.get("source_title"), 500), title)
        if score < 0.9:
            continue
        matches.append(
            {
                "source_ref_id": compact(evidence.get("source_ref_id"), 160),
                "source_hash": compact(evidence.get("source_hash"), 160),
                "source_account": compact(evidence.get("source_account"), 220),
                "source_title": compact(evidence.get("source_title"), 500),
                "post_date": compact(evidence.get("post_date"), 80),
                "public_url_allowed": bool(evidence.get("public_url_allowed")),
                "title_match_score": round(score, 4),
                "title_match_strategy": strategy,
            }
        )
    matches.sort(key=lambda item: (-item["title_match_score"], item["post_date"], item["source_ref_id"]))
    return matches[:limit]


def performance_events_for_refs(conn: sqlite3.Connection, source_ref_ids: list[str]) -> list[dict[str, Any]]:
    if not source_ref_ids or not table_exists(conn, "performance_event"):
        return []
    events: list[dict[str, Any]] = []
    for source_ref_id in source_ref_ids:
        rows = conn.execute(
            """
            SELECT event_id, event_title, starts_at, time_text, venue_name, city,
                   source_ref_id, participant_count, organizer_count, confidence
            FROM performance_event
            WHERE source_ref_id = ?
            ORDER BY starts_at DESC, event_title
            LIMIT 20
            """,
            (source_ref_id,),
        ).fetchall()
        events.extend(rowdict(row) for row in rows)
    return events


def participants_for_events(conn: sqlite3.Connection, event_ids: list[str], limit: int = 16) -> list[dict[str, Any]]:
    if not event_ids or not table_exists(conn, "dj_event") or not table_exists(conn, "dj_profile"):
        return []
    participants: list[dict[str, Any]] = []
    for event_id in event_ids:
        rows = conn.execute(
            """
            SELECT de.event_id, de.dj_id, dp.display_name, de.confidence
            FROM dj_event de
            LEFT JOIN dj_profile dp ON dp.dj_id = de.dj_id
            WHERE de.event_id = ?
            ORDER BY dp.display_name, de.dj_id
            LIMIT ?
            """,
            (event_id, limit),
        ).fetchall()
        for row in rows:
            participants.append(
                {
                    "event_id": compact(row["event_id"], 140),
                    "dj_id": compact(row["dj_id"], 140),
                    "display_name": compact(row["display_name"], 220),
                    "confidence": row["confidence"],
                }
            )
    return participants[:limit]


def review_row(
    *,
    conn: sqlite3.Connection,
    row: dict[str, Any],
    account_evidence: list[dict[str, Any]],
    selected_accounts: list[str],
    generated_at: str,
) -> dict[str, Any]:
    source_matches = best_source_matches(row, account_evidence)
    source_ref_ids = [match["source_ref_id"] for match in source_matches]
    all_events = performance_events_for_refs(conn, source_ref_ids)
    event_candidates: list[dict[str, Any]] = []
    for event in all_events:
        score, strategy = event_match(compact(event.get("event_title"), 320), compact(row.get("name"), 320))
        if score >= 0.72:
            event_candidates.append(
                {
                    "event_id": compact(event.get("event_id"), 140),
                    "event_title": compact(event.get("event_title"), 320),
                    "starts_at": compact(event.get("starts_at"), 80),
                    "time_text": compact(event.get("time_text"), 120),
                    "venue_name": compact(event.get("venue_name"), 220),
                    "city": compact(event.get("city"), 120),
                    "source_ref_id": compact(event.get("source_ref_id"), 160),
                    "participant_count": number(event.get("participant_count")),
                    "organizer_count": number(event.get("organizer_count")),
                    "confidence": event.get("confidence"),
                    "event_match_score": round(score, 4),
                    "event_match_strategy": strategy,
                }
            )
    event_candidates.sort(key=lambda item: (-item["event_match_score"], item["event_id"]))
    event_candidates = event_candidates[:5]
    participants = participants_for_events(conn, [event["event_id"] for event in event_candidates], limit=16)
    participant_count = len(participants)

    if not source_matches:
        review_status = "source_ocr_recovery_required"
        blocker = "No selected serving source_ref matched the work-order source account and title strongly enough."
        next_gate = "Recover source article/OCR/Markdown evidence before participant acceptance precheck."
        precheck_candidate = False
    elif not all_events:
        review_status = "source_context_found_event_reextract_required"
        blocker = "The article source_ref matched, but no performance_event rows exist for the source_ref."
        next_gate = "Run source-context re-extract or event-shell repair before participant acceptance precheck."
        precheck_candidate = False
    elif not event_candidates:
        review_status = "source_context_found_manual_event_match_required"
        blocker = "The article has performance_event rows, but none matched the candidate event name strongly enough."
        next_gate = "Manual event-name review is required before participant acceptance precheck."
        precheck_candidate = False
    elif participant_count == 0:
        review_status = "event_context_found_participant_repair_required"
        blocker = "Matched event context exists, but no participant rows were found in dj_event."
        next_gate = "Repair participant extraction before source/graph acceptance."
        precheck_candidate = False
    else:
        review_status = "deterministic_acceptance_precheck_candidate"
        blocker = "none"
        next_gate = "Run a separate deterministic acceptance precheck packet; keep all write gates closed until it passes."
        precheck_candidate = True

    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "work_item_id": compact(row.get("work_item_id"), 120),
        "rank": number(row.get("rank")),
        "article_uid": compact(row.get("article_uid"), 220),
        "source_account": compact(row.get("source_account"), 220),
        "source_account_selected_for_review": compact(row.get("source_account"), 220) in selected_accounts,
        "title": compact(row.get("title"), 520),
        "name": compact(row.get("name"), 320),
        "triage_bucket": compact(row.get("triage_bucket"), 160),
        "review_priority_score": number(row.get("review_priority_score")),
        "source_match_rows": len(source_matches),
        "source_matches": source_matches,
        "matched_performance_event_rows": len(all_events),
        "matched_event_candidate_rows": len(event_candidates),
        "matched_event_candidates": event_candidates,
        "participant_sample_rows": participant_count,
        "participant_samples": participants,
        "review_status": review_status,
        "blocking_reason": blocker,
        "deterministic_acceptance_precheck_candidate": precheck_candidate,
        "accepted_for_graph": False,
        "source_sqlite_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_status": "report_only",
        "next_gate": next_gate,
    }


def source_account_review_batches(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["source_account"]].append(row)
    batches: list[dict[str, Any]] = []
    for account, account_rows in grouped.items():
        status_counts = Counter(row["review_status"] for row in account_rows)
        batches.append(
            {
                "schema_version": SCHEMA_VERSION + ".source_account_batch",
                "source_account": account,
                "review_rows": len(account_rows),
                "deterministic_acceptance_precheck_candidate_rows": status_counts.get(
                    "deterministic_acceptance_precheck_candidate", 0
                ),
                "source_ocr_recovery_required_rows": status_counts.get("source_ocr_recovery_required", 0),
                "status_counts": dict(sorted(status_counts.items())),
                "top_work_item_ids": [row["work_item_id"] for row in account_rows[:5]],
                "write_status": "report_only",
                "next_gate": "Run deterministic acceptance precheck only for candidate rows; keep source/OCR recovery rows blocked.",
            }
        )
    batches.sort(
        key=lambda row: (
            -row["deterministic_acceptance_precheck_candidate_rows"],
            -row["review_rows"],
            row["source_account"],
        )
    )
    return batches


def leak_scan(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    hits = {"public_url_hits": 0, "secret_word_hits": 0, "local_path_hits": 0}
    for row in rows:
        text = json.dumps(row, ensure_ascii=False, sort_keys=True)
        hits["public_url_hits"] += len(URL_RE.findall(text))
        hits["secret_word_hits"] += len(SECRET_RE.findall(text))
        hits["local_path_hits"] += len(LOCAL_PATH_RE.findall(text))
    return hits


def markdown_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Atlas T6 Manual Participant Source-Context Review",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Selected source accounts: `{summary['selected_source_accounts']}`",
        f"- Input work-order rows: `{summary['counts']['input_work_order_rows']}`",
        f"- Reviewed rows: `{summary['counts']['reviewed_rows']}`",
        f"- Deterministic acceptance precheck candidate rows: `{summary['counts']['deterministic_acceptance_precheck_candidate_rows']}`",
        f"- Source/OCR recovery required rows: `{summary['counts']['source_ocr_recovery_required_rows']}`",
        f"- Public URL / secret / local path leak hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['secret_word_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Review Status Counts",
        "",
    ]
    for key, value in sorted(summary["review_status_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Source Account Batches", ""])
    for row in summary["source_account_batches"][:10]:
        lines.append(
            "- `{source_account}` rows `{review_rows}` precheck-candidates `{candidate_rows}` statuses `{statuses}`".format(
                source_account=row["source_account"],
                review_rows=row["review_rows"],
                candidate_rows=row["deterministic_acceptance_precheck_candidate_rows"],
                statuses=row["status_counts"],
            )
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Report-only local source-context/manual-evidence review for selected manual participant work orders.",
            "- Serving SQLite was opened read-only; no source/raw Atlas DB mutation, serving SQLite rebuild/write, graph/vector/DB production write, public pointer, deploy, upload/review, memory write, credential read, network/model/paid API, destructive Git, 9router use, or D: root scan occurred.",
            "- Candidate rows are only eligible for a future deterministic acceptance precheck; they are not accepted graph facts.",
            "",
        ]
    )
    return "\n".join(lines)


def build_review(
    *,
    work_orders_path: Path,
    batch_queue_path: Path,
    serving_db: Path,
    out_dir: Path,
    report_path: Path,
    source_accounts: list[str],
    top_batches: int,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    generated_at = now_iso()
    work_orders = read_jsonl(work_orders_path)
    batch_rows = read_jsonl(batch_queue_path)
    selected_accounts = choose_source_accounts(batch_rows, source_accounts, top_batches)
    selected_rows = [row for row in work_orders if compact(row.get("source_account"), 220) in selected_accounts]
    selected_rows.sort(key=lambda row: (-number(row.get("review_priority_score")), number(row.get("rank")), compact(row.get("work_item_id"))))

    with connect_serving_db(serving_db) as conn:
        account_evidence = load_account_evidence(conn, selected_accounts)
        review_rows = [
            review_row(
                conn=conn,
                row=row,
                account_evidence=account_evidence.get(compact(row.get("source_account"), 220), []),
                selected_accounts=selected_accounts,
                generated_at=generated_at,
            )
            for row in selected_rows
        ]

    precheck_candidates = [
        row for row in review_rows if row["review_status"] == "deterministic_acceptance_precheck_candidate"
    ]
    source_ocr_recovery = [row for row in review_rows if row["review_status"] == "source_ocr_recovery_required"]
    blocked_rows = [row for row in review_rows if row["review_status"] != "deterministic_acceptance_precheck_candidate"]
    account_batches = source_account_review_batches(review_rows)
    review_status_counts = Counter(row["review_status"] for row in review_rows)
    leaks = leak_scan(review_rows + account_batches)
    failed_checks = [key for key, value in leaks.items() if value]
    decision = (
        "atlas_social_manual_participant_source_context_review_candidates_ready_report_only"
        if precheck_candidates and not failed_checks
        else "atlas_social_manual_participant_source_context_review_blocked_report_only"
        if not failed_checks
        else "atlas_social_manual_participant_source_context_review_failed_safety_scan"
    )
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {
            "work_orders_jsonl": display_path(work_orders_path),
            "source_account_batch_queue_jsonl": display_path(batch_queue_path),
            "serving_db": display_path(serving_db),
        },
        "outputs": {
            "summary_json": display_path(out_dir / "manual_participant_source_context_review_summary.json"),
            "review_rows_jsonl": display_path(out_dir / "manual_participant_source_context_review_rows.jsonl"),
            "deterministic_acceptance_precheck_candidates_jsonl": display_path(
                out_dir / "deterministic_acceptance_precheck_candidates.jsonl"
            ),
            "source_context_blocked_rows_jsonl": display_path(out_dir / "source_context_blocked_rows.jsonl"),
            "source_ocr_recovery_needed_rows_jsonl": display_path(out_dir / "source_ocr_recovery_needed_rows.jsonl"),
            "source_account_review_batches_jsonl": display_path(out_dir / "source_account_review_batches.jsonl"),
            "report_md": display_path(report_path),
        },
        "selected_source_accounts": selected_accounts,
        "counts": {
            "input_work_order_rows": len(work_orders),
            "input_source_account_batches": len(batch_rows),
            "selected_source_accounts": len(selected_accounts),
            "reviewed_rows": len(review_rows),
            "deterministic_acceptance_precheck_candidate_rows": len(precheck_candidates),
            "source_context_blocked_rows": len(blocked_rows),
            "source_ocr_recovery_required_rows": len(source_ocr_recovery),
            "matched_source_ref_rows": sum(1 for row in review_rows if row["source_match_rows"] > 0),
            "matched_event_candidate_rows": sum(1 for row in review_rows if row["matched_event_candidate_rows"] > 0),
        },
        "review_status_counts": dict(sorted(review_status_counts.items())),
        "source_account_batches": account_batches,
        "leak_scan": leaks,
        "safety": {
            "report_only": True,
            "serving_sqlite_read_only": True,
            "network_call_executed": False,
            "llm_call_executed": False,
            "paid_api_call_executed": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
        "stop_reason": "none" if not failed_checks else "safety_scan_failed",
        "wait_reason": "precheck candidates still require a separate deterministic acceptance gate; blocked rows need source/OCR/manual recovery.",
        "next_resume_cursor": display_path(out_dir / "deterministic_acceptance_precheck_candidates.jsonl")
        if precheck_candidates
        else display_path(out_dir / "source_context_blocked_rows.jsonl"),
    }

    write_jsonl(out_dir / "manual_participant_source_context_review_rows.jsonl", review_rows)
    write_jsonl(out_dir / "deterministic_acceptance_precheck_candidates.jsonl", precheck_candidates)
    write_jsonl(out_dir / "source_context_blocked_rows.jsonl", blocked_rows)
    write_jsonl(out_dir / "source_ocr_recovery_needed_rows.jsonl", source_ocr_recovery)
    write_jsonl(out_dir / "source_account_review_batches.jsonl", account_batches)
    write_json(out_dir / "manual_participant_source_context_review_summary.json", summary)
    write_text(report_path, markdown_report(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-orders", type=Path, default=DEFAULT_WORK_ORDERS)
    parser.add_argument("--source-account-batches", type=Path, default=DEFAULT_BATCHES)
    parser.add_argument("--serving-db", type=Path, default=DEFAULT_SERVING_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--source-account", action="append", default=[], help="Specific source account to review. Can be repeated.")
    parser.add_argument("--top-batches", type=int, default=len(DEFAULT_SOURCE_ACCOUNTS))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    requested = args.source_account or DEFAULT_SOURCE_ACCOUNTS
    summary = build_review(
        work_orders_path=args.work_orders,
        batch_queue_path=args.source_account_batches,
        serving_db=args.serving_db,
        out_dir=args.out_dir,
        report_path=args.report,
        source_accounts=requested,
        top_batches=args.top_batches,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
