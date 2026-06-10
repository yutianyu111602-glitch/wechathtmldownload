#!/usr/bin/env python3
"""Build a third-pass Atlas entity merge queue from residual review rows.

The second pass accepts many partial merges but leaves the original review rows
in the augmented plan. This script separates already-absorbed reviews from real
residual candidates, then emits only the residual candidate subsets for another
direct DeepSeek run. It is report-only and never mutates Atlas data.
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


SCHEMA_VERSION = "atlas_entity_merge_third_pass_queue.v1"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_QUEUE = REPO_ROOT / "reports" / "atlas_entity_merge_deepseek_second_pass_queue_current" / "entity_merge_augmented_queue.jsonl"
DEFAULT_REVIEW = REPO_ROOT / "reports" / "atlas_entity_merge_plan_ocr_full_secondpass_current" / "entity_merge_review_queue.jsonl"
DEFAULT_GROUPS = REPO_ROOT / "reports" / "atlas_entity_merge_plan_ocr_full_secondpass_current" / "entity_merge_groups_report_only.jsonl"
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_entity_merge_deepseek_third_pass_queue_current"


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


HARD_GUARDRAIL_REASONS = {
    "compound_multi_entity_label_blocked",
    "dj_non_dj_merge_blocked",
    "sound_system_entity_label_blocked",
}
HARD_GUARDRAIL_FLAGS = {
    "mixed_subject_types",
    "mixed_type_merge",
    "dj_place_org_mix",
    "compound_multi_entity_label_blocked",
    "sound_system_entity_label_blocked",
}


def load_subject_group_owner(groups_path: Path) -> dict[str, str]:
    owner: dict[str, str] = {}
    for group in read_jsonl(groups_path):
        group_id = text(group.get("group_id")) or text(group.get("canonical_subject_id"))
        for member in group.get("members") or []:
            subject_id = text(member.get("subject_id")) if isinstance(member, dict) else ""
            if subject_id and group_id:
                owner[subject_id] = group_id
    return owner


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


def candidate_subject_ids(merged_ids: list[str], subjects: dict[str, dict[str, Any]], max_members: int) -> list[str]:
    unique_ids = [subject_id for subject_id in text_list(merged_ids) if subject_id in subjects]
    return sorted(unique_ids, key=lambda subject_id: (-member_score(subjects[subject_id]), subject_id))[:max_members]


def absorption_status(merged_ids: list[str], subject_owner: dict[str, str]) -> str:
    if not merged_ids:
        return "no_merged_ids"
    owners = [subject_owner.get(subject_id, "") for subject_id in sorted(set(merged_ids))]
    owned = [owner for owner in owners if owner]
    if len(owned) == len(owners) and len(set(owned)) == 1:
        return "merged_ids_all_absorbed"
    if len(owned) == len(owners):
        return "merged_ids_in_groups_but_not_same_group"
    if owned:
        return "merged_ids_partly_absorbed"
    return "merged_ids_unabsorbed"


def hard_guardrail_hit(review: dict[str, Any], reason: str) -> bool:
    if reason in HARD_GUARDRAIL_REASONS:
        return True
    return bool(set(text_list(review.get("risk_flags"))) & HARD_GUARDRAIL_FLAGS)


def closure_decision(review: dict[str, Any], *, status: str, pass_label: str, reason: str, confidence: float, reason_zh: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".closure",
        "cluster_id": text(review.get("cluster_id")),
        "closure_status": status,
        "source_pass": pass_label,
        "review_reason": reason,
        "decision": "split",
        "execute": True,
        "confidence": confidence,
        "canonical_subject_id": "",
        "canonical_name": "",
        "merged_subject_ids": [],
        "blocked_subject_ids": text_list(review.get("blocked_subject_ids")),
        "reason_zh": reason_zh,
        "risk_flags": unique_flags(review.get("risk_flags") or [], f"third_pass_closure:{status}"),
        "report_only": True,
    }


def build_third_pass_queue(args: argparse.Namespace) -> dict[str, Any]:
    queue_path = Path(args.queue)
    review_path = Path(args.review)
    groups_path = Path(args.groups)
    out_dir = Path(args.out_dir)
    min_members = max(2, int(args.min_members))
    max_members = max(min_members, int(args.max_members))
    max_rows = max(0, int(args.max_rows))
    include_blocked_context = bool(args.include_blocked_context)

    original_rows, clusters, subjects = load_queue(queue_path)
    review_rows = read_jsonl(review_path)
    subject_owner = load_subject_group_owner(groups_path)
    rows: list[dict[str, Any]] = []
    closure_rows: list[dict[str, Any]] = []
    deferred_rows: list[dict[str, Any]] = []
    candidate_seen: set[str] = set()
    counts = Counter()
    skipped = Counter()

    for review in review_rows:
        source_cluster_id = text(review.get("cluster_id"))
        source_cluster = clusters.get(source_cluster_id) or {}
        merged_ids = [subject_id for subject_id in text_list(review.get("merged_subject_ids")) if subject_id in subjects]
        status = absorption_status(merged_ids, subject_owner)
        pass_label = "secondpass" if "::secondpass::" in source_cluster_id else "original"
        reason = text(review.get("review_reason")) or "review"
        counts[f"status:{status}"] += 1
        counts[f"status_pass:{status}:{pass_label}"] += 1
        counts[f"review_reason:{reason}"] += 1
        if status == "merged_ids_all_absorbed":
            closure_rows.append(
                closure_decision(
                    review,
                    status=status,
                    pass_label=pass_label,
                    reason=reason,
                    confidence=0.99,
                    reason_zh="已由二阶段子集合并吸收，原大簇不再整体合并。",
                )
            )
            continue
        if status == "no_merged_ids":
            if hard_guardrail_hit(review, reason):
                counts["hard_guardrail_keep"] += 1
                closure_rows.append(
                    closure_decision(
                        review,
                        status="hard_guardrail_keep",
                        pass_label=pass_label,
                        reason=reason,
                        confidence=0.99,
                        reason_zh="无可合并子集且命中硬护栏，保留为不自动合并。",
                    )
                )
            else:
                counts["deferred_ambiguous_no_action"] += 1
                deferred_rows.append({**review, "deferred_reason": "ambiguous_no_merged_ids"})
            continue

        candidate_ids = candidate_subject_ids(merged_ids, subjects, max_members)
        if len(candidate_ids) < min_members:
            skipped["without_candidate_members"] += 1
            continue
        digest = candidate_key(candidate_ids)
        if digest in candidate_seen:
            skipped["duplicate_candidate_set"] += 1
            closure_rows.append(
                closure_decision(
                    review,
                    status="duplicate_candidate_set_queued",
                    pass_label=pass_label,
                    reason=reason,
                    confidence=0.9,
                    reason_zh="相同候选子集已进入第三阶段队列，本行关闭为重复复判入口。",
                )
            )
            continue
        candidate_seen.add(digest)

        members = [subjects[subject_id] for subject_id in candidate_ids]
        canonical_id = text(review.get("canonical_subject_id"))
        canonical = subjects.get(canonical_id) if canonical_id in candidate_ids else None
        if canonical is None:
            canonical = max(members, key=member_score)
        blocked_ids = text_list(review.get("blocked_subject_ids"))
        context_blocked = [subjects[subject_id] for subject_id in blocked_ids if subject_id in subjects][:12] if include_blocked_context else []
        rows.append(
            {
                "schema_version": SCHEMA_VERSION + ".cluster",
                "source_schema_version": source_cluster.get("schema_version") or "",
                "cluster_id": f"{source_cluster_id}::thirdpass::{digest}",
                "source_cluster_id": source_cluster_id,
                "block_key": text(review.get("block_key")) or text(source_cluster.get("block_key")),
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
                "risk_flags": unique_flags(
                    source_cluster.get("risk_flags") or [],
                    review.get("risk_flags") or [],
                    f"previous_review_reason:{reason}",
                    f"third_pass_absorption_status:{status}",
                    "third_pass_residual_review",
                ),
                "llm_task": "Third-pass residual adjudication: make a final conservative call for these remaining candidate subjects.",
                "members": members,
                "second_pass_context": {
                    "source_cluster_id": source_cluster_id,
                    "source_pass": pass_label,
                    "previous_decision": text(review.get("decision")),
                    "previous_review_reason": reason,
                    "previous_reason_zh": text(review.get("reason_zh"))[:240],
                    "previous_canonical_subject_id": text(review.get("canonical_subject_id")),
                    "previous_merged_subject_ids": candidate_ids,
                    "absorption_status": status,
                    "context_blocked_members": context_blocked,
                    "goal": "Return merge only if every current member is one real-world entity. If not, split. Use review only for true evidence contradiction.",
                },
                "output_contract": {
                    "decision": "merge|split|review",
                    "canonical_subject_id": "must be one of current members when merge",
                    "merged_subject_ids": "only current members; non-merge decisions should leave this empty",
                    "blocked_subject_ids": "current members that must not merge",
                    "risk_flags": "include mixed_type_merge when venue and organizer/radio are merged",
                },
            }
        )
        counts["residual_candidate_queued"] += 1
        closure_rows.append(
            closure_decision(
                review,
                status="residual_candidate_queued",
                pass_label=pass_label,
                reason=reason,
                confidence=0.95,
                reason_zh="已抽取候选子集进入第三阶段终审，原大簇关闭为不整体合并；第三阶段子簇结果单独进入合并计划。",
            )
        )
        if max_rows and len(rows) >= max_rows:
            skipped["stopped_by_max_rows"] += 1
            break

    out_dir.mkdir(parents=True, exist_ok=True)
    third_queue_path = out_dir / "entity_merge_third_pass_queue.jsonl"
    closure_path = out_dir / "entity_merge_review_closure_decisions.jsonl"
    deferred_path = out_dir / "entity_merge_deferred_review_rows.jsonl"
    augmented_queue_path = out_dir / "entity_merge_third_pass_augmented_queue.jsonl"
    write_jsonl(third_queue_path, rows)
    write_jsonl(closure_path, closure_rows)
    write_jsonl(deferred_path, deferred_rows)
    write_jsonl(augmented_queue_path, [*original_rows, *rows])
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "atlas_entity_merge_third_pass_queue_ready_report_only",
        "queue_path": str(queue_path),
        "review_path": str(review_path),
        "groups_path": str(groups_path),
        "out_dir": str(out_dir),
        "input_queue_rows": len(original_rows),
        "review_rows": len(review_rows),
        "closure_rows": len(closure_rows),
        "deferred_rows": len(deferred_rows),
        "third_pass_rows": len(rows),
        "augmented_queue_rows": len(original_rows) + len(rows),
        "min_members": min_members,
        "max_members": max_members,
        "max_rows": max_rows,
        "counts": dict(counts),
        "skipped": dict(skipped),
        "third_pass_queue_path": str(third_queue_path),
        "closure_decisions_path": str(closure_path),
        "deferred_review_path": str(deferred_path),
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
    write_json(out_dir / "entity_merge_third_pass_queue_summary.json", summary)
    write_markdown(out_dir / "entity_merge_third_pass_queue_report.md", summary, rows[:20])
    return summary


def write_markdown(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Atlas Entity Merge Third Pass Queue",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- review_rows: `{summary['review_rows']}`",
        f"- closure_rows: `{summary['closure_rows']}`",
        f"- deferred_rows: `{summary['deferred_rows']}`",
        f"- third_pass_rows: `{summary['third_pass_rows']}`",
        f"- augmented_queue_rows: `{summary['augmented_queue_rows']}`",
        "",
        "## Counts",
        "",
    ]
    for key, value in sorted(summary["counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Sample Queue Rows", ""])
    for row in rows:
        lines.append(
            f"- `{row['cluster_id']}` members `{row['member_count']}` flags `{row.get('risk_flags')}`"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This queue is report-only.",
            "- No DeepSeek call, SQLite write, Neo4j write, Qdrant write, mem0 write, or production pointer update.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--groups", type=Path, default=DEFAULT_GROUPS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--min-members", type=int, default=2)
    parser.add_argument("--max-members", type=int, default=16)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--include-blocked-context", action="store_true", default=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    summary = build_third_pass_queue(parse_args(argv))
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
