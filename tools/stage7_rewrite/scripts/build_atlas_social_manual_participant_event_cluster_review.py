#!/usr/bin/env python3
"""Build a report-only event-id / event-cluster review packet for Q6 participant rows."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_PRECHECK_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_acceptance_precheck_q6_20260526"
DEFAULT_EVENT_ID_DEDUPE = DEFAULT_PRECHECK_DIR / "event_id_dedupe_review_rows.jsonl"
DEFAULT_AMBIGUOUS = DEFAULT_PRECHECK_DIR / "ambiguous_event_cluster_review_rows.jsonl"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_event_cluster_review_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_EVENT_CLUSTER_REVIEW_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_event_cluster_review.v1"

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
    "dadabeijing": "dada北京",
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
        raise ValueError(f"{label} must not point to D: for manual participant event-cluster review: {path}")


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


def stable_id(prefix: str, parts: Iterable[Any]) -> str:
    raw = "|".join(compact(part, 500) for part in parts)
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def cluster_signature(cluster: dict[str, Any]) -> dict[str, Any]:
    return {
        "cluster_id": compact(cluster.get("cluster_id"), 120),
        "event_title_sample": compact(cluster.get("event_title_sample"), 260),
        "starts_at": compact(cluster.get("starts_at"), 80),
        "venue_name_sample": compact(cluster.get("venue_name_sample"), 160),
        "city_sample": compact(cluster.get("city_sample"), 80),
        "event_ids": [compact(item, 120) for item in cluster.get("event_ids", []) if compact(item, 120)],
        "event_id_count": int(number(cluster.get("event_id_count"))),
        "candidate_rows": int(number(cluster.get("candidate_rows"))),
        "max_event_match_score": round(number(cluster.get("max_event_match_score")), 4),
        "max_participant_count": int(number(cluster.get("max_participant_count"))),
        "source_ref_ids": [compact(item, 120) for item in cluster.get("source_ref_ids", []) if compact(item, 120)][:8],
    }


def title_similarity(clusters: list[dict[str, Any]]) -> float:
    titles = [normalize(cluster.get("event_title_sample")) for cluster in clusters if normalize(cluster.get("event_title_sample"))]
    if len(titles) <= 1:
        return 1.0
    best = max(titles, key=len)
    ratios: list[float] = []
    for title in titles:
        if title == best or title in best or best in title:
            ratios.append(1.0)
        else:
            ratios.append(SequenceMatcher(None, best, title).ratio())
    return min(ratios) if ratios else 0.0


def all_same(values: Iterable[str]) -> bool:
    cleaned = {value for value in values if value}
    return len(cleaned) <= 1


def choose_representative_event_id(clusters: list[dict[str, Any]]) -> str:
    candidates: list[tuple[int, int, float, str]] = []
    for cluster in clusters:
        for event_id in cluster.get("event_ids", []):
            candidates.append(
                (
                    int(number(cluster.get("max_participant_count"))),
                    int(number(cluster.get("candidate_rows"))),
                    number(cluster.get("max_event_match_score")),
                    compact(event_id, 120),
                )
            )
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
    return candidates[0][3]


def write_closed_flags() -> dict[str, bool | str]:
    return {
        "accepted_for_graph": False,
        "source_sqlite_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_status": "report_only",
    }


def review_event_id_dedupe_row(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    clusters = [cluster_signature(item) for item in row.get("semantic_event_clusters", []) if isinstance(item, dict)]
    event_ids = sorted({event_id for cluster in clusters for event_id in cluster["event_ids"]})
    status = "event_id_consolidation_candidate_report_only"
    blocker = "none"
    if len(clusters) != 1:
        status = "blocked_unexpected_cluster_count"
        blocker = "event-id dedupe input must contain exactly one semantic cluster"
    elif len(event_ids) <= 1:
        status = "blocked_no_duplicate_event_ids"
        blocker = "event-id dedupe input did not contain multiple event ids"
    elif not bool(row.get("evidence_gate_passed")):
        status = "blocked_evidence_gate_not_passed"
        blocker = "source, event, and participant evidence gates must all pass before event-id consolidation review"
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "review_lane": "event_id_dedupe",
        "review_status": status,
        "blocking_reason": blocker,
        "consolidation_review_id": stable_id(
            "evtconsolidation",
            [row.get("article_uid"), row.get("work_item_id"), ",".join(event_ids), status],
        ),
        "source_account": compact(row.get("source_account"), 220),
        "article_uid": compact(row.get("article_uid"), 260),
        "work_item_id": compact(row.get("work_item_id"), 100),
        "rank": int(number(row.get("rank"))),
        "title": compact(row.get("title"), 520),
        "name": compact(row.get("name"), 320),
        "source_ref_id": compact(row.get("best_source_match", {}).get("source_ref_id"), 140),
        "source_hash": compact(row.get("best_source_match", {}).get("source_hash"), 140),
        "post_date": compact(row.get("best_source_match", {}).get("post_date"), 80),
        "semantic_event_cluster_count": len(clusters),
        "event_id_count": len(event_ids),
        "candidate_rows": sum(int(number(cluster.get("candidate_rows"))) for cluster in clusters),
        "participant_sample_rows": int(number(row.get("participant_sample_rows"))),
        "representative_event_id_review_only": choose_representative_event_id(clusters),
        "event_ids_for_consolidation_review": event_ids[:20],
        "semantic_event_clusters": clusters[:8],
        "event_id_consolidation_candidate": status == "event_id_consolidation_candidate_report_only",
        "semantic_cluster_consolidation_candidate": False,
        "manual_event_identity_blocked": status != "event_id_consolidation_candidate_report_only",
        "next_gate": "Run a separate DB-backed event-id consolidation gate before graph fact acceptance or serving rebuild.",
        **write_closed_flags(),
    }


def review_ambiguous_row(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    clusters = [cluster_signature(item) for item in row.get("semantic_event_clusters", []) if isinstance(item, dict)]
    event_ids = sorted({event_id for cluster in clusters for event_id in cluster["event_ids"]})
    starts_same = all_same(compact(cluster.get("starts_at"), 80) for cluster in clusters)
    city_same = all_same(normalize(cluster.get("city_sample")) for cluster in clusters)
    venue_same = all_same(normalize_venue(cluster.get("venue_name_sample")) for cluster in clusters)
    title_min_similarity = round(title_similarity(clusters), 4)

    status = "semantic_cluster_consolidation_candidate_report_only"
    blocker = "none"
    if len(clusters) <= 1:
        status = "blocked_unexpected_cluster_count"
        blocker = "ambiguous input must contain more than one semantic cluster"
    elif not bool(row.get("evidence_gate_passed")):
        status = "blocked_evidence_gate_not_passed"
        blocker = "source, event, and participant evidence gates must all pass before semantic cluster consolidation review"
    elif not starts_same:
        status = "blocked_conflicting_event_dates"
        blocker = "candidate clusters disagree on starts_at"
    elif not city_same or not venue_same:
        status = "blocked_conflicting_city_or_venue"
        blocker = "candidate clusters disagree on normalized city or venue"
    elif title_min_similarity < 0.72:
        status = "blocked_low_title_similarity"
        blocker = "candidate clusters need manual title/event identity review"

    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "review_lane": "ambiguous_event_cluster",
        "review_status": status,
        "blocking_reason": blocker,
        "consolidation_review_id": stable_id(
            "evtclusterreview",
            [row.get("article_uid"), row.get("work_item_id"), ",".join(event_ids), status],
        ),
        "source_account": compact(row.get("source_account"), 220),
        "article_uid": compact(row.get("article_uid"), 260),
        "work_item_id": compact(row.get("work_item_id"), 100),
        "rank": int(number(row.get("rank"))),
        "title": compact(row.get("title"), 520),
        "name": compact(row.get("name"), 320),
        "source_ref_id": compact(row.get("best_source_match", {}).get("source_ref_id"), 140),
        "source_hash": compact(row.get("best_source_match", {}).get("source_hash"), 140),
        "post_date": compact(row.get("best_source_match", {}).get("post_date"), 80),
        "semantic_event_cluster_count": len(clusters),
        "event_id_count": len(event_ids),
        "candidate_rows": sum(int(number(cluster.get("candidate_rows"))) for cluster in clusters),
        "participant_sample_rows": int(number(row.get("participant_sample_rows"))),
        "representative_event_id_review_only": choose_representative_event_id(clusters),
        "event_ids_for_consolidation_review": event_ids[:24],
        "semantic_event_clusters": clusters[:8],
        "cluster_date_consistent": starts_same,
        "cluster_city_consistent": city_same,
        "cluster_venue_consistent": venue_same,
        "cluster_title_min_similarity": title_min_similarity,
        "event_id_consolidation_candidate": False,
        "semantic_cluster_consolidation_candidate": status == "semantic_cluster_consolidation_candidate_report_only",
        "manual_event_identity_blocked": status != "semantic_cluster_consolidation_candidate_report_only",
        "next_gate": "Run a separate semantic cluster consolidation gate before graph fact acceptance or serving rebuild.",
        **write_closed_flags(),
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
        statuses = Counter(row["review_status"] for row in values)
        batches.append(
            {
                "schema_version": SCHEMA_VERSION + ".source_account_batch",
                "source_account": source_account,
                "input_rows": len(values),
                "event_id_consolidation_candidate_rows": sum(
                    1 for row in values if row["event_id_consolidation_candidate"]
                ),
                "semantic_cluster_consolidation_candidate_rows": sum(
                    1 for row in values if row["semantic_cluster_consolidation_candidate"]
                ),
                "manual_event_identity_blocked_rows": sum(
                    1 for row in values if row["manual_event_identity_blocked"]
                ),
                "status_counts": dict(sorted(statuses.items())),
                "top_consolidation_review_ids": [row["consolidation_review_id"] for row in values[:8]],
                "write_status": "report_only",
                "next_gate": "Use consolidation candidates only as input to a later explicit gate; do not accept graph facts from this packet.",
            }
        )
    return batches


def markdown_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    lines = [
        "# Atlas T6 Manual Participant Event Cluster Review",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Input event-id dedupe rows: `{counts['input_event_id_dedupe_rows']}`",
        f"- Input ambiguous-cluster rows: `{counts['input_ambiguous_event_cluster_rows']}`",
        f"- Event-id consolidation candidate rows: `{counts['event_id_consolidation_candidate_rows']}`",
        f"- Semantic cluster consolidation candidate rows: `{counts['semantic_cluster_consolidation_candidate_rows']}`",
        f"- Manual event identity blocked rows: `{counts['manual_event_identity_blocked_rows']}`",
        f"- Public URL / sensitive-key / local path leak hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['secret_word_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Review Status Counts",
        "",
    ]
    for key, value in sorted(summary["review_status_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Output Cursors",
            "",
            f"- all review rows: `{summary['outputs']['event_cluster_review_rows_jsonl']}`",
            f"- event-id consolidation candidates: `{summary['outputs']['event_id_consolidation_candidates_jsonl']}`",
            f"- semantic cluster consolidation candidates: `{summary['outputs']['semantic_cluster_consolidation_candidates_jsonl']}`",
            f"- blocked rows: `{summary['outputs']['manual_event_identity_blocked_rows_jsonl']}`",
            f"- source-account batches: `{summary['outputs']['source_account_batches_jsonl']}`",
            "",
            "## LLM Audit Finding",
            "",
            "- The 05:55 precheck split the candidate rows correctly, but the next useful action is not acceptance. It is event identity normalization.",
            "- Single semantic-cluster rows with multiple event IDs can feed a later DB-backed event-id consolidation gate.",
            "- Multi-cluster rows are only consolidation candidates when the clusters agree on date, city, venue, and have high title similarity; otherwise they remain blocked for manual event identity review.",
            "",
            "## Boundary",
            "",
            "- Report-only review over existing redacted JSONL artifacts.",
            "- No source/raw Atlas DB mutation, serving SQLite read/write/rebuild, Neo4j/Qdrant/SQLite production write, public pointer, deploy, upload/review, memory write, credential read, network/model/paid API, 9router use, or D: root scan occurred.",
            "",
            f"- Next resume cursor: {summary['next_resume_cursor']}",
            "",
        ]
    )
    return "\n".join(lines)


def build_event_cluster_review(
    event_id_dedupe_path: Path, ambiguous_path: Path, out_dir: Path, report_path: Path
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    reject_d_path(report_path, "report_path")
    generated_at = now_iso()
    event_id_inputs = read_jsonl(event_id_dedupe_path)
    ambiguous_inputs = read_jsonl(ambiguous_path)
    rows = [review_event_id_dedupe_row(row, generated_at) for row in event_id_inputs]
    rows.extend(review_ambiguous_row(row, generated_at) for row in ambiguous_inputs)

    event_id_candidates = [row for row in rows if row["event_id_consolidation_candidate"]]
    semantic_candidates = [row for row in rows if row["semantic_cluster_consolidation_candidate"]]
    blocked_rows = [row for row in rows if row["manual_event_identity_blocked"]]
    source_batches = batch_rows(rows)
    leaks = leak_scan(rows)
    failed_checks = [key for key, value in leaks.items() if value]
    status_counts = Counter(row["review_status"] for row in rows)
    decision = (
        "atlas_social_manual_participant_event_cluster_review_failed_safety_scan"
        if failed_checks
        else "atlas_social_manual_participant_event_cluster_review_candidates_ready_report_only"
        if event_id_candidates or semantic_candidates
        else "atlas_social_manual_participant_event_cluster_review_blocked_report_only"
    )
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {
            "event_id_dedupe_rows_jsonl": display_path(event_id_dedupe_path),
            "ambiguous_event_cluster_rows_jsonl": display_path(ambiguous_path),
        },
        "outputs": {
            "summary_json": display_path(out_dir / "manual_participant_event_cluster_review_summary.json"),
            "event_cluster_review_rows_jsonl": display_path(out_dir / "manual_participant_event_cluster_review_rows.jsonl"),
            "event_id_consolidation_candidates_jsonl": display_path(out_dir / "event_id_consolidation_candidates.jsonl"),
            "semantic_cluster_consolidation_candidates_jsonl": display_path(
                out_dir / "semantic_cluster_consolidation_candidates.jsonl"
            ),
            "manual_event_identity_blocked_rows_jsonl": display_path(out_dir / "manual_event_identity_blocked_rows.jsonl"),
            "source_account_batches_jsonl": display_path(out_dir / "source_account_event_cluster_review_batches.jsonl"),
            "report_md": display_path(report_path),
        },
        "counts": {
            "input_event_id_dedupe_rows": len(event_id_inputs),
            "input_ambiguous_event_cluster_rows": len(ambiguous_inputs),
            "review_rows": len(rows),
            "event_id_consolidation_candidate_rows": len(event_id_candidates),
            "semantic_cluster_consolidation_candidate_rows": len(semantic_candidates),
            "manual_event_identity_blocked_rows": len(blocked_rows),
            "source_account_batches": len(source_batches),
            "accepted_for_graph_rows": 0,
            "source_sqlite_write_allowed_rows": 0,
            "serving_rebuild_allowed_rows": 0,
            "graph_write_allowed_rows": 0,
            "public_serving_field_allowed_rows": 0,
            "memory_write_allowed_rows": 0,
        },
        "review_status_counts": dict(sorted(status_counts.items())),
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
            "event-id consolidation and semantic cluster consolidation candidates still require a later explicit gate before any graph fact acceptance."
            if event_id_candidates or semantic_candidates
            else "manual event identity review required before any graph fact acceptance."
        ),
        "next_resume_cursor": (
            "Process tools/stage7_rewrite/reports/atlas_social_manual_participant_event_cluster_review_q6_20260526/"
            "event_id_consolidation_candidates.jsonl first, then semantic_cluster_consolidation_candidates.jsonl; "
            "manual_event_identity_blocked_rows.jsonl remains closed for manual/source review. All write gates remain closed."
        ),
    }

    write_jsonl(out_dir / "manual_participant_event_cluster_review_rows.jsonl", rows)
    write_jsonl(out_dir / "event_id_consolidation_candidates.jsonl", event_id_candidates)
    write_jsonl(out_dir / "semantic_cluster_consolidation_candidates.jsonl", semantic_candidates)
    write_jsonl(out_dir / "manual_event_identity_blocked_rows.jsonl", blocked_rows)
    write_jsonl(out_dir / "source_account_event_cluster_review_batches.jsonl", source_batches)
    write_json(out_dir / "manual_participant_event_cluster_review_summary.json", summary)
    write_text(out_dir / "manual_participant_event_cluster_review_summary.md", markdown_report(summary))
    write_text(report_path, markdown_report(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-id-dedupe", type=Path, default=DEFAULT_EVENT_ID_DEDUPE)
    parser.add_argument("--ambiguous", type=Path, default=DEFAULT_AMBIGUOUS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_event_cluster_review(args.event_id_dedupe, args.ambiguous, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if summary["failed_checks"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
