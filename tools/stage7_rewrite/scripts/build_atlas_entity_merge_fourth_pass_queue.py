#!/usr/bin/env python3
"""Build a fourth-pass final review queue for Atlas entity merge.

This pass consumes the currently validated third-pass plan review rows. It
closes deterministic non-merge rows as split decisions and emits only the
remaining ambiguous rows for one final direct DeepSeek review. It is report-only
and never mutates Atlas data.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "atlas_entity_merge_fourth_pass_queue.v1"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_QUEUE = REPO_ROOT / "reports" / "atlas_entity_merge_deepseek_third_pass_queue_current" / "entity_merge_third_pass_augmented_queue.jsonl"
DEFAULT_REVIEW = REPO_ROOT / "reports" / "atlas_entity_merge_plan_ocr_full_thirdpass_current" / "entity_merge_review_queue.jsonl"
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_entity_merge_fourth_pass_queue_current"

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


def load_queue(queue_path: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows = read_jsonl(queue_path)
    clusters: dict[str, dict[str, Any]] = {}
    for row in rows:
        cluster_id = text(row.get("cluster_id"))
        if cluster_id:
            clusters[cluster_id] = row
    return rows, clusters


def unique_flags(*values: Any) -> list[str]:
    flags: list[str] = []
    for value in values:
        if isinstance(value, list):
            flags.extend(text_list(value))
        else:
            item = text(value)
            if item:
                flags.append(item)
    return text_list(flags)


def member_ids(cluster: dict[str, Any]) -> list[str]:
    return [text(member.get("subject_id")) for member in cluster.get("members") or [] if text(member.get("subject_id"))]


def hard_guardrail_hit(review: dict[str, Any], reason: str) -> bool:
    if reason in HARD_GUARDRAIL_REASONS:
        return True
    return bool(set(text_list(review.get("risk_flags"))) & HARD_GUARDRAIL_FLAGS)


def closure_decision(
    review: dict[str, Any],
    cluster: dict[str, Any],
    *,
    status: str,
    reason: str,
    confidence: float,
    reason_zh: str,
) -> dict[str, Any]:
    blocked = text_list(review.get("blocked_subject_ids")) or member_ids(cluster)
    return {
        "schema_version": SCHEMA_VERSION + ".closure",
        "cluster_id": text(review.get("cluster_id")),
        "closure_status": status,
        "review_reason": reason,
        "decision": "split",
        "execute": True,
        "confidence": confidence,
        "canonical_subject_id": "",
        "canonical_name": "",
        "merged_subject_ids": [],
        "blocked_subject_ids": blocked,
        "reason_zh": reason_zh,
        "risk_flags": unique_flags(review.get("risk_flags") or [], f"fourth_pass_closure:{status}"),
        "report_only": True,
    }


def should_close_without_llm(review: dict[str, Any], cluster: dict[str, Any]) -> tuple[bool, str, str]:
    reason = text(review.get("review_reason")) or "review"
    raw_decision = text(review.get("raw_llm_decision")) or text(review.get("decision"))
    merged_ids = text_list(review.get("merged_subject_ids"))
    flags = set(text_list(review.get("risk_flags")))
    if hard_guardrail_hit(review, reason):
        return True, "hard_guardrail_final_keep", "命中硬护栏，第四阶段关闭为不自动合并。"
    if raw_decision == "split" and len(merged_ids) < 2:
        return True, "nonmerge_singleton_closed", "模型已判定拆分且没有有效多成员合并，第四阶段关闭为不合并。"
    if raw_decision == "merge" and len(merged_ids) < 2:
        return True, "merge_without_multiple_members_closed", "合并决策没有有效多成员集合，第四阶段关闭为不合并。"
    if "llm_output_inconsistent_nonmerge_with_merged_ids" in flags and len(merged_ids) < 2:
        return True, "inconsistent_nonmerge_singleton_closed", "非合并输出只带单个候选成员，第四阶段关闭为不合并。"
    if not member_ids(cluster):
        return True, "missing_cluster_members_closed", "找不到可复判成员，第四阶段关闭为不合并。"
    return False, "", ""


def build_fourth_pass_queue(args: argparse.Namespace) -> dict[str, Any]:
    queue_path = Path(args.queue)
    review_path = Path(args.review)
    out_dir = Path(args.out_dir)
    max_members = max(2, int(args.max_members))

    original_rows, clusters = load_queue(queue_path)
    review_rows = read_jsonl(review_path)
    rows: list[dict[str, Any]] = []
    closure_rows: list[dict[str, Any]] = []
    counts = Counter()
    skipped = Counter()

    for review in review_rows:
        cluster_id = text(review.get("cluster_id"))
        cluster = clusters.get(cluster_id) or {}
        reason = text(review.get("review_reason")) or "review"
        raw_decision = text(review.get("raw_llm_decision")) or text(review.get("decision"))
        counts[f"review_reason:{reason}"] += 1
        counts[f"raw_decision:{raw_decision}"] += 1

        close, status, reason_zh = should_close_without_llm(review, cluster)
        if close:
            counts[f"closure:{status}"] += 1
            closure_rows.append(
                closure_decision(
                    review,
                    cluster,
                    status=status,
                    reason=reason,
                    confidence=0.99,
                    reason_zh=reason_zh,
                )
            )
            continue

        members = list(cluster.get("members") or [])[:max_members]
        if len(members) < 2:
            skipped["without_candidate_members"] += 1
            closure_rows.append(
                closure_decision(
                    review,
                    cluster,
                    status="without_candidate_members_closed",
                    reason=reason,
                    confidence=0.99,
                    reason_zh="少于两个可复判成员，第四阶段关闭为不合并。",
                )
            )
            continue
        rows.append(
            {
                "schema_version": SCHEMA_VERSION + ".cluster",
                "source_schema_version": cluster.get("schema_version") or "",
                "cluster_id": cluster_id,
                "source_cluster_id": cluster_id,
                "block_key": text(review.get("block_key")) or text(cluster.get("block_key")),
                "block_member_count": cluster.get("block_member_count") or 0,
                "cluster_part_index": cluster.get("cluster_part_index") or 0,
                "cluster_part_count": cluster.get("cluster_part_count") or 1,
                "member_count": len(members),
                "canonical_hint": cluster.get("canonical_hint") or {},
                "risk_flags": unique_flags(
                    cluster.get("risk_flags") or [],
                    review.get("risk_flags") or [],
                    f"previous_review_reason:{reason}",
                    "fourth_pass_final_review",
                ),
                "llm_task": "Fourth-pass final review closure: merge only if every current member is one real-world entity; otherwise close as split.",
                "members": members,
                "fourth_pass_context": {
                    "previous_decision": text(review.get("decision")),
                    "previous_raw_llm_decision": raw_decision,
                    "previous_review_reason": reason,
                    "previous_reason_zh": text(review.get("reason_zh"))[:260],
                    "previous_merged_subject_ids": text_list(review.get("merged_subject_ids")),
                    "goal": "Do not leave ordinary uncertainty as review. After prior passes, insufficient evidence means split/no merge. Use review only for explicit contradictory evidence that cannot be safely split.",
                },
                "output_contract": {
                    "decision": "merge|split|review",
                    "canonical_subject_id": "must be one of current members when merge",
                    "merged_subject_ids": "merge must include every current member; non-merge decisions leave this empty",
                    "blocked_subject_ids": "current members that must not merge",
                    "risk_flags": "include mixed_type_merge only when venue and organizer/radio are intentionally merged",
                },
            }
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    queue_out = out_dir / "entity_merge_fourth_pass_queue.jsonl"
    closure_out = out_dir / "entity_merge_fourth_pass_closure_decisions.jsonl"
    write_jsonl(queue_out, rows)
    write_jsonl(closure_out, closure_rows)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "atlas_entity_merge_fourth_pass_queue_ready_report_only",
        "queue_path": str(queue_path),
        "review_path": str(review_path),
        "out_dir": str(out_dir),
        "input_queue_rows": len(original_rows),
        "review_rows": len(review_rows),
        "closure_rows": len(closure_rows),
        "fourth_pass_rows": len(rows),
        "max_members": max_members,
        "counts": dict(counts),
        "skipped": dict(skipped),
        "fourth_pass_queue_path": str(queue_out),
        "closure_decisions_path": str(closure_out),
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
    write_json(out_dir / "entity_merge_fourth_pass_queue_summary.json", summary)
    write_markdown(out_dir / "entity_merge_fourth_pass_queue_report.md", summary, rows[:20])
    return summary


def write_markdown(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Atlas Entity Merge Fourth Pass Queue",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- review_rows: `{summary['review_rows']}`",
        f"- closure_rows: `{summary['closure_rows']}`",
        f"- fourth_pass_rows: `{summary['fourth_pass_rows']}`",
        "",
        "## Counts",
        "",
    ]
    for key, value in sorted(summary["counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Sample Queue Rows", ""])
    for row in rows:
        lines.append(f"- `{row['cluster_id']}` members `{row['member_count']}` flags `{row.get('risk_flags')}`")
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
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--max-members", type=int, default=24)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    summary = build_fourth_pass_queue(parse_args(argv))
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
