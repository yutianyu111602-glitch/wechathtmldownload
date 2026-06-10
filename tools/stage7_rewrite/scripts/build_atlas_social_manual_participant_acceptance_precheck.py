#!/usr/bin/env python3
"""Build a report-only deterministic acceptance precheck for Q6 participant rows."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_INPUT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_source_context_review_q6_20260526"
    / "deterministic_acceptance_precheck_candidates.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_acceptance_precheck_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_ACCEPTANCE_PRECHECK_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_acceptance_precheck.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)

VENUE_ALIASES = {
    "oil油": "oil",
    "oil": "oil",
    "dada昆明": "dada昆明",
    "dadakunming": "dada昆明",
    "dada北京": "dada北京",
    "dadabarbeijing": "dada北京",
    "dada": "dada",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def normalize(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", compact(value, 1000).casefold())


def normalize_venue(value: Any) -> str:
    normalized = normalize(value)
    return VENUE_ALIASES.get(normalized, normalized)


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for manual participant acceptance precheck: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "input_jsonl")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: expected object row")
            rows.append(value)
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


def strongest_source_match(source_matches: list[dict[str, Any]]) -> dict[str, Any]:
    if not source_matches:
        return {}
    return max(
        source_matches,
        key=lambda row: (
            number(row.get("title_match_score")),
            0 if "weak" in compact(row.get("title_match_strategy")).casefold() else 1,
            compact(row.get("post_date")),
            compact(row.get("source_ref_id")),
        ),
    )


def qualifying_event_candidates(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    qualified: list[dict[str, Any]] = []
    for event in events:
        if number(event.get("event_match_score")) < 0.9:
            continue
        if number(event.get("participant_count")) <= 0:
            continue
        if not compact(event.get("event_id")) or not compact(event.get("starts_at")):
            continue
        if not compact(event.get("venue_name")):
            continue
        qualified.append(event)
    return qualified


def cluster_key(event: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        normalize(event.get("event_title")),
        compact(event.get("starts_at"), 40),
        normalize_venue(event.get("venue_name")),
        normalize(event.get("city")),
    )


def cluster_digest(key: tuple[str, str, str, str]) -> str:
    raw = "|".join(key)
    return "evtcluster:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def summarize_clusters(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[cluster_key(event)].append(event)
    clusters: list[dict[str, Any]] = []
    for key, values in grouped.items():
        event_ids = sorted({compact(event.get("event_id"), 120) for event in values if compact(event.get("event_id"))})
        title_sample = compact(values[0].get("event_title"), 260) if values else ""
        venue_sample = compact(values[0].get("venue_name"), 160) if values else ""
        city_sample = compact(values[0].get("city"), 80) if values else ""
        source_refs = sorted({compact(event.get("source_ref_id"), 120) for event in values if compact(event.get("source_ref_id"))})
        clusters.append(
            {
                "cluster_id": cluster_digest(key),
                "event_title_sample": title_sample,
                "starts_at": key[1],
                "venue_name_sample": venue_sample,
                "city_sample": city_sample,
                "event_ids": event_ids,
                "event_id_count": len(event_ids),
                "candidate_rows": len(values),
                "max_event_match_score": max(round(number(event.get("event_match_score")), 4) for event in values),
                "max_participant_count": max(int(number(event.get("participant_count"))) for event in values),
                "source_ref_ids": source_refs[:8],
            }
        )
    clusters.sort(key=lambda item: (-item["max_event_match_score"], item["starts_at"], item["cluster_id"]))
    return clusters


def source_gate_passed(row: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    matches = row.get("source_matches") if isinstance(row.get("source_matches"), list) else []
    best = strongest_source_match([item for item in matches if isinstance(item, dict)])
    if not matches:
        return False, "missing_source_match", {}
    if number(best.get("title_match_score")) < 0.94:
        return False, "weak_source_title_match", best
    if "weak" in compact(best.get("title_match_strategy")).casefold():
        return False, "weak_source_title_strategy", best
    return True, "source_match_passed", best


def participant_gate_passed(participants: list[dict[str, Any]], qualified_events: list[dict[str, Any]]) -> bool:
    qualified_event_ids = {compact(event.get("event_id"), 120) for event in qualified_events}
    for participant in participants:
        if compact(participant.get("event_id"), 120) in qualified_event_ids and compact(participant.get("dj_id"), 120):
            return True
    return False


def classify_row(input_row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    source_matches = input_row.get("source_matches") if isinstance(input_row.get("source_matches"), list) else []
    event_candidates = (
        input_row.get("matched_event_candidates") if isinstance(input_row.get("matched_event_candidates"), list) else []
    )
    participants = input_row.get("participant_samples") if isinstance(input_row.get("participant_samples"), list) else []
    source_ok, source_status, best_source = source_gate_passed(input_row)
    qualified_events = qualifying_event_candidates([item for item in event_candidates if isinstance(item, dict)])
    participant_ok = participant_gate_passed([item for item in participants if isinstance(item, dict)], qualified_events)
    clusters = summarize_clusters(qualified_events)
    event_ids = sorted({event_id for cluster in clusters for event_id in cluster["event_ids"]})

    gate_status = "strict_manual_acceptance_review_ready"
    blocker = "none"
    if not bool(input_row.get("deterministic_acceptance_precheck_candidate")):
        gate_status = "blocked_not_precheck_candidate"
        blocker = "input row was not marked as a deterministic acceptance precheck candidate"
    elif not source_ok:
        gate_status = "blocked_source_evidence_required"
        blocker = source_status
    elif not qualified_events:
        gate_status = "blocked_event_evidence_required"
        blocker = "no qualifying event candidate has score>=0.9, participant_count>0, starts_at, and venue"
    elif not participant_ok:
        gate_status = "blocked_participant_evidence_required"
        blocker = "participant samples do not tie a DJ id to a qualifying event id"
    elif len(clusters) > 1:
        gate_status = "ambiguous_event_cluster_review_required"
        blocker = "multiple semantic event clusters match this source row"
    elif len(event_ids) > 1:
        gate_status = "semantic_duplicate_event_id_dedupe_required"
        blocker = "one semantic event cluster maps to multiple event ids and needs dedupe review"

    strict_ready = gate_status == "strict_manual_acceptance_review_ready"
    dedupe_required = gate_status in {
        "semantic_duplicate_event_id_dedupe_required",
        "ambiguous_event_cluster_review_required",
    }
    evidence_gate_passed = source_ok and bool(qualified_events) and participant_ok
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "work_item_id": compact(input_row.get("work_item_id"), 100),
        "rank": int(number(input_row.get("rank"))),
        "article_uid": compact(input_row.get("article_uid"), 260),
        "source_account": compact(input_row.get("source_account"), 220),
        "title": compact(input_row.get("title"), 520),
        "name": compact(input_row.get("name"), 320),
        "source_match_rows": int(number(input_row.get("source_match_rows"))) or len(source_matches),
        "matched_event_candidate_rows": int(number(input_row.get("matched_event_candidate_rows")))
        or len(event_candidates),
        "participant_sample_rows": int(number(input_row.get("participant_sample_rows"))) or len(participants),
        "best_source_match": {
            "source_ref_id": compact(best_source.get("source_ref_id"), 140),
            "source_hash": compact(best_source.get("source_hash"), 140),
            "source_account": compact(best_source.get("source_account"), 220),
            "post_date": compact(best_source.get("post_date"), 80),
            "title_match_score": round(number(best_source.get("title_match_score")), 4),
            "title_match_strategy": compact(best_source.get("title_match_strategy"), 120),
            "public_url_allowed": False,
        },
        "source_gate_passed": source_ok,
        "event_gate_passed": bool(qualified_events),
        "participant_gate_passed": participant_ok,
        "evidence_gate_passed": evidence_gate_passed,
        "qualified_event_candidate_rows": len(qualified_events),
        "qualified_event_id_count": len(event_ids),
        "semantic_event_cluster_count": len(clusters),
        "semantic_event_clusters": clusters[:8],
        "gate_status": gate_status,
        "blocking_reason": blocker,
        "strict_manual_acceptance_review_ready": strict_ready,
        "event_id_dedupe_review_required": gate_status == "semantic_duplicate_event_id_dedupe_required",
        "ambiguous_event_cluster_review_required": gate_status == "ambiguous_event_cluster_review_required",
        "dedupe_or_ambiguity_review_required": dedupe_required,
        "deterministic_acceptance_precheck_passed": strict_ready,
        "accepted_for_graph": False,
        "source_sqlite_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_status": "report_only",
        "next_gate": (
            "Run a separate manual acceptance/rebuild gate for strict-ready rows; run event-id dedupe or ambiguity review first for all dedupe rows. Keep all write gates closed."
        ),
    }


def leak_scan(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        text = json.dumps(row, ensure_ascii=False, sort_keys=True)
        counts["public_url_hits"] += len(URL_RE.findall(text))
        counts["secret_word_hits"] += len(SECRET_RE.findall(text))
        counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(text))
    return dict(counts)


def batch_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["source_account"]].append(row)
    batches: list[dict[str, Any]] = []
    for source_account, values in sorted(grouped.items()):
        statuses = Counter(row["gate_status"] for row in values)
        batches.append(
            {
                "schema_version": SCHEMA_VERSION + ".source_account_batch",
                "source_account": source_account,
                "input_rows": len(values),
                "strict_manual_acceptance_review_ready_rows": sum(
                    1 for row in values if row["strict_manual_acceptance_review_ready"]
                ),
                "event_id_dedupe_review_rows": sum(1 for row in values if row["event_id_dedupe_review_required"]),
                "ambiguous_event_cluster_review_rows": sum(
                    1 for row in values if row["ambiguous_event_cluster_review_required"]
                ),
                "blocked_rows": sum(
                    1
                    for row in values
                    if not row["strict_manual_acceptance_review_ready"]
                    and not row["dedupe_or_ambiguity_review_required"]
                ),
                "status_counts": dict(sorted(statuses.items())),
                "top_work_item_ids": [row["work_item_id"] for row in values[:8]],
                "write_status": "report_only",
                "next_gate": "Use strict rows only for a later manual acceptance gate; resolve event-id dedupe/ambiguity before any write.",
            }
        )
    return batches


def markdown_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    lines = [
        "# Atlas T6 Manual Participant Acceptance Precheck",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Input candidate rows: `{counts['input_candidate_rows']}`",
        f"- Strict manual acceptance review-ready rows: `{counts['strict_manual_acceptance_review_ready_rows']}`",
        f"- Semantic duplicate event-id dedupe rows: `{counts['event_id_dedupe_review_rows']}`",
        f"- Ambiguous event-cluster review rows: `{counts['ambiguous_event_cluster_review_rows']}`",
        f"- Blocked rows: `{counts['blocked_rows']}`",
        f"- Public URL / secret / local path leak hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['secret_word_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Gate Status Counts",
        "",
    ]
    for key, value in sorted(summary["gate_status_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Output Cursors",
            "",
            f"- rows: `{summary['outputs']['precheck_rows_jsonl']}`",
            f"- strict-ready rows: `{summary['outputs']['strict_manual_acceptance_review_ready_jsonl']}`",
            f"- event-id dedupe rows: `{summary['outputs']['event_id_dedupe_review_rows_jsonl']}`",
            f"- ambiguous-cluster rows: `{summary['outputs']['ambiguous_event_cluster_review_rows_jsonl']}`",
            f"- blocked rows: `{summary['outputs']['blocked_rows_jsonl']}`",
            "",
            "## LLM Audit Finding",
            "",
            "- The 05:36 source-context review was consistent and leak-clean, but many candidate rows matched multiple local event IDs.",
            "- This precheck therefore does not accept graph facts. It separates strict rows from semantic duplicate or ambiguous event clusters before any later acceptance, serving rebuild, graph/vector write, public pointer, deploy, upload/review, or memory promotion.",
            "",
            "## Boundary",
            "",
            "- Report-only deterministic precheck over existing candidate JSONL.",
            "- No source/raw Atlas DB mutation, serving SQLite read/write/rebuild, Neo4j/Qdrant/SQLite production write, public pointer, deploy, upload/review, memory write, credential read, network/model/paid API, 9router use, or D: root scan occurred.",
            "",
            f"- Next resume cursor: {summary['next_resume_cursor']}",
            "",
        ]
    )
    return "\n".join(lines)


def build_precheck(input_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    reject_d_path(report_path, "report_path")
    generated_at = now_iso()
    inputs = read_jsonl(input_path)
    rows = [classify_row(row, generated_at) for row in inputs]
    strict_rows = [row for row in rows if row["strict_manual_acceptance_review_ready"]]
    dedupe_rows = [row for row in rows if row["event_id_dedupe_review_required"]]
    ambiguous_rows = [row for row in rows if row["ambiguous_event_cluster_review_required"]]
    blocked_rows = [
        row
        for row in rows
        if not row["strict_manual_acceptance_review_ready"] and not row["dedupe_or_ambiguity_review_required"]
    ]
    source_batches = batch_rows(rows)
    leaks = leak_scan(rows)
    failed_checks = [key for key, value in leaks.items() if value]
    status_counts = Counter(row["gate_status"] for row in rows)
    decision = (
        "atlas_social_manual_participant_acceptance_precheck_failed_safety_scan"
        if failed_checks
        else "atlas_social_manual_participant_acceptance_precheck_review_ready_report_only"
        if strict_rows or dedupe_rows or ambiguous_rows
        else "atlas_social_manual_participant_acceptance_precheck_blocked_report_only"
    )
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {
            "deterministic_acceptance_precheck_candidates_jsonl": display_path(input_path),
        },
        "outputs": {
            "summary_json": display_path(out_dir / "manual_participant_acceptance_precheck_summary.json"),
            "precheck_rows_jsonl": display_path(out_dir / "manual_participant_acceptance_precheck_rows.jsonl"),
            "strict_manual_acceptance_review_ready_jsonl": display_path(
                out_dir / "strict_manual_acceptance_review_ready.jsonl"
            ),
            "event_id_dedupe_review_rows_jsonl": display_path(out_dir / "event_id_dedupe_review_rows.jsonl"),
            "ambiguous_event_cluster_review_rows_jsonl": display_path(
                out_dir / "ambiguous_event_cluster_review_rows.jsonl"
            ),
            "blocked_rows_jsonl": display_path(out_dir / "blocked_manual_participant_acceptance_rows.jsonl"),
            "source_account_batches_jsonl": display_path(out_dir / "source_account_acceptance_precheck_batches.jsonl"),
            "report_md": display_path(report_path),
        },
        "counts": {
            "input_candidate_rows": len(inputs),
            "precheck_rows": len(rows),
            "strict_manual_acceptance_review_ready_rows": len(strict_rows),
            "event_id_dedupe_review_rows": len(dedupe_rows),
            "ambiguous_event_cluster_review_rows": len(ambiguous_rows),
            "dedupe_or_ambiguity_review_required_rows": len(dedupe_rows) + len(ambiguous_rows),
            "blocked_rows": len(blocked_rows),
            "source_account_batches": len(source_batches),
            "accepted_for_graph_rows": 0,
            "source_sqlite_write_allowed_rows": 0,
            "serving_rebuild_allowed_rows": 0,
            "graph_write_allowed_rows": 0,
            "public_serving_field_allowed_rows": 0,
            "memory_write_allowed_rows": 0,
        },
        "gate_status_counts": dict(sorted(status_counts.items())),
        "leak_scan": leaks,
        "safety": {
            "report_only": True,
            "network_call_executed": False,
            "llm_call_executed": False,
            "paid_api_call_executed": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_read_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
        "stop_reason": "none" if not failed_checks else "safety_scan_failed",
        "wait_reason": (
            "event-id dedupe or ambiguous event-cluster review is required before any graph fact acceptance for non-strict rows."
            if dedupe_rows or ambiguous_rows
            else "none"
        ),
        "next_resume_cursor": (
            "Process tools/stage7_rewrite/reports/atlas_social_manual_participant_acceptance_precheck_q6_20260526/event_id_dedupe_review_rows.jsonl "
            "and ambiguous_event_cluster_review_rows.jsonl first; only strict_manual_acceptance_review_ready.jsonl may feed a later manual acceptance gate, and all write gates remain closed."
        ),
    }

    write_jsonl(out_dir / "manual_participant_acceptance_precheck_rows.jsonl", rows)
    write_jsonl(out_dir / "strict_manual_acceptance_review_ready.jsonl", strict_rows)
    write_jsonl(out_dir / "event_id_dedupe_review_rows.jsonl", dedupe_rows)
    write_jsonl(out_dir / "ambiguous_event_cluster_review_rows.jsonl", ambiguous_rows)
    write_jsonl(out_dir / "blocked_manual_participant_acceptance_rows.jsonl", blocked_rows)
    write_jsonl(out_dir / "source_account_acceptance_precheck_batches.jsonl", source_batches)
    write_json(out_dir / "manual_participant_acceptance_precheck_summary.json", summary)
    write_text(out_dir / "manual_participant_acceptance_precheck_summary.md", markdown_report(summary))
    write_text(report_path, markdown_report(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_precheck(args.input, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if summary["failed_checks"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
