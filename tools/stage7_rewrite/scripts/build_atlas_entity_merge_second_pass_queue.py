#!/usr/bin/env python3
"""Build a second-pass Atlas entity merge queue from first-pass review rows.

The first DeepSeek pass can identify a mergeable subset while still returning
``review`` for the whole large cluster. This script extracts those subset
candidates into smaller report-only clusters that can be adjudicated by a
second direct DeepSeek run. It never mutates Atlas SQLite or production state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "atlas_entity_merge_second_pass_queue.v1"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_QUEUE = REPO_ROOT / "reports" / "atlas_entity_merge_deepseek_queue_ocr_full_current" / "entity_merge_llm_queue.jsonl"
DEFAULT_REVIEW = REPO_ROOT / "reports" / "atlas_entity_merge_plan_ocr_full_current" / "entity_merge_review_queue.jsonl"
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_entity_merge_deepseek_second_pass_queue_current"


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def text(value: Any) -> str:
    return str(value or "").strip()


def text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        item_text = text(item)
        if item_text and item_text not in seen:
            seen.add(item_text)
            out.append(item_text)
    return out


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, dict):
                raise ValueError(f"invalid JSONL object at {path}:{line_no}")
            rows.append(row)
    return rows


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
            count += 1
        tmp = Path(handle.name)
    tmp.replace(path)
    return count


def load_queue(queue_path: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    rows = read_jsonl(queue_path)
    clusters: dict[str, dict[str, Any]] = {}
    subjects: dict[str, dict[str, Any]] = {}
    for row in rows:
        cluster_id = text(row.get("cluster_id"))
        if cluster_id:
            clusters[cluster_id] = row
        for member in row.get("members") or []:
            subject_id = text(member.get("subject_id"))
            if subject_id and subject_id not in subjects:
                subjects[subject_id] = member
    return rows, clusters, subjects


def member_score(member: dict[str, Any]) -> float:
    metrics = member.get("metrics") if isinstance(member.get("metrics"), dict) else {}
    try:
        return float(metrics.get("rank_score") or member.get("rank_score") or 0)
    except (TypeError, ValueError):
        return 0.0


def unique_flags(*values: Any) -> list[str]:
    return text_list([flag for value in values for flag in (value if isinstance(value, list) else [value])])


def candidate_key(subject_ids: list[str]) -> str:
    return hashlib.sha1("\n".join(sorted(subject_ids)).encode("utf-8")).hexdigest()[:12]


def build_second_pass_queue(args: argparse.Namespace) -> dict[str, Any]:
    queue_path = Path(args.queue)
    review_path = Path(args.review)
    out_dir = Path(args.out_dir)
    min_members = max(2, int(args.min_members))
    max_members = max(min_members, int(args.max_members))
    max_rows = max(0, int(args.max_rows))
    include_blocked_context = bool(args.include_blocked_context)

    original_rows, clusters, subjects = load_queue(queue_path)
    review_rows = read_jsonl(review_path)
    rows: list[dict[str, Any]] = []
    candidate_seen: set[str] = set()
    counts = Counter()
    skipped = Counter()

    for review in review_rows:
        source_cluster_id = text(review.get("cluster_id"))
        merged_ids = [subject_id for subject_id in text_list(review.get("merged_subject_ids")) if subject_id in subjects]
        if len(merged_ids) < min_members:
            skipped["without_partial_merge_ids"] += 1
            continue
        merged_ids = sorted(set(merged_ids), key=lambda subject_id: member_score(subjects[subject_id]), reverse=True)[:max_members]
        if len(merged_ids) < min_members:
            skipped["after_cap_without_min_members"] += 1
            continue
        digest = candidate_key(merged_ids)
        if digest in candidate_seen:
            skipped["duplicate_candidate_set"] += 1
            continue
        candidate_seen.add(digest)

        members = [subjects[subject_id] for subject_id in merged_ids]
        canonical = None
        canonical_id = text(review.get("canonical_subject_id"))
        if canonical_id in merged_ids:
            canonical = subjects[canonical_id]
        if canonical is None:
            canonical = max(members, key=member_score)
        source_cluster = clusters.get(source_cluster_id) or {}
        blocked_ids = text_list(review.get("blocked_subject_ids"))
        context_blocked = [subjects[subject_id] for subject_id in blocked_ids if subject_id in subjects][:12] if include_blocked_context else []
        risk_flags = unique_flags(
            source_cluster.get("risk_flags") or [],
            review.get("risk_flags") or [],
            f"first_pass_review_reason:{text(review.get('review_reason')) or 'review'}",
            "second_pass_partial_merge_review",
        )
        block_key = text(review.get("block_key")) or text(source_cluster.get("block_key"))
        rows.append(
            {
                "schema_version": SCHEMA_VERSION + ".cluster",
                "source_schema_version": source_cluster.get("schema_version") or "",
                "cluster_id": f"{source_cluster_id}::secondpass::{digest}",
                "source_cluster_id": source_cluster_id,
                "block_key": block_key,
                "block_member_count": source_cluster.get("block_member_count") or 0,
                "cluster_part_index": 0,
                "cluster_part_count": 1,
                "member_count": len(members),
                "canonical_hint": {
                    "subject_id": canonical.get("subject_id"),
                    "subject_type": canonical.get("subject_type"),
                    "display_name": canonical.get("display_name"),
                    "rank_score": member_score(canonical),
                },
                "risk_flags": risk_flags,
                "llm_task": "Second-pass subset adjudication: decide whether these candidate subjects are all the same real-world Atlas entity.",
                "members": members,
                "second_pass_context": {
                    "source_cluster_id": source_cluster_id,
                    "previous_decision": text(review.get("decision")),
                    "previous_review_reason": text(review.get("review_reason")),
                    "previous_reason_zh": text(review.get("reason_zh"))[:240],
                    "previous_canonical_subject_id": text(review.get("canonical_subject_id")),
                    "previous_merged_subject_ids": merged_ids,
                    "context_blocked_members": context_blocked,
                    "goal": "If and only if every current member is the same entity, return merge. Otherwise split or review.",
                },
                "output_contract": {
                    "decision": "merge|split|review",
                    "canonical_subject_id": "must be one of current members when merge",
                    "merged_subject_ids": "only current members that are all the same entity",
                    "blocked_subject_ids": "current members that must not merge",
                    "risk_flags": "include mixed_type_merge when venue and organizer/radio are merged",
                },
            }
        )
        counts[f"review_reason:{text(review.get('review_reason')) or 'review'}"] += 1
        for flag in text_list(review.get("risk_flags")):
            counts[f"risk_flag:{flag}"] += 1
        if max_rows and len(rows) >= max_rows:
            skipped["stopped_by_max_rows"] += max(0, len(review_rows) - (sum(counts.values()) + sum(skipped.values())))
            break

    out_dir.mkdir(parents=True, exist_ok=True)
    second_queue_path = out_dir / "entity_merge_second_pass_queue.jsonl"
    augmented_queue_path = out_dir / "entity_merge_augmented_queue.jsonl"
    write_jsonl(second_queue_path, rows)
    write_jsonl(augmented_queue_path, [*original_rows, *rows])
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "atlas_entity_merge_second_pass_queue_ready_report_only",
        "queue_path": str(queue_path),
        "review_path": str(review_path),
        "out_dir": str(out_dir),
        "original_queue_rows": len(original_rows),
        "review_rows": len(review_rows),
        "second_pass_rows": len(rows),
        "augmented_queue_rows": len(original_rows) + len(rows),
        "min_members": min_members,
        "max_members": max_members,
        "max_rows": max_rows,
        "counts": dict(counts),
        "skipped": dict(skipped),
        "second_pass_queue_path": str(second_queue_path),
        "augmented_queue_path": str(augmented_queue_path),
        "safety": {
            "report_only": True,
            "llm_call_executed": False,
            "sqlite_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "production_pointer_updated": False,
        },
    }
    write_json(out_dir / "entity_merge_second_pass_queue_summary.json", summary)
    write_markdown(out_dir / "entity_merge_second_pass_queue_report.md", summary, rows[:20])
    return summary


def write_markdown(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Atlas Entity Merge Second Pass Queue",
        "",
        f"- decision: `{summary['decision']}`",
        f"- review_rows: `{summary['review_rows']}`",
        f"- second_pass_rows: `{summary['second_pass_rows']}`",
        f"- augmented_queue_rows: `{summary['augmented_queue_rows']}`",
        "",
        "## Sample Rows",
        "",
    ]
    for row in rows:
        labels = ", ".join(text(member.get("display_name")) for member in row.get("members", [])[:8])
        lines.append(f"- `{row['cluster_id']}` / `{row['block_key']}`: {row['member_count']} members; {labels}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", default=str(DEFAULT_QUEUE))
    parser.add_argument("--review", default=str(DEFAULT_REVIEW))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--min-members", type=int, default=2)
    parser.add_argument("--max-members", type=int, default=16)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--include-blocked-context", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    summary = build_second_pass_queue(parse_args(argv))
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
