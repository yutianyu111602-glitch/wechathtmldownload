#!/usr/bin/env python3
"""Build a report-only Atlas entity merge plan from DeepSeek decisions.

This consumes the full entity merge queue plus streamed DeepSeek decisions and
materializes merge groups, review rows, and split rows. It never mutates Atlas
SQLite, Neo4j, Qdrant, mem0, or production pointers.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "atlas_entity_merge_plan_from_deepseek.v1"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_QUEUE = REPO_ROOT / "reports" / "atlas_entity_merge_deepseek_queue_ocr_full_current" / "entity_merge_llm_queue.jsonl"
DEFAULT_DECISIONS = REPO_ROOT / "reports" / "atlas_entity_merge_deepseek_results_ocr_full_current" / "entity_merge_llm_decisions.jsonl"
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_entity_merge_plan_ocr_full_current"


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def text(value: Any) -> str:
    return str(value or "").strip()


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


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        if item not in self.parent:
            self.parent[item] = item
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left


def load_queue(queue_path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    subjects: dict[str, dict[str, Any]] = {}
    clusters: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(queue_path):
        cluster_id = text(row.get("cluster_id"))
        if cluster_id:
            clusters[cluster_id] = row
        for member in row.get("members") or []:
            subject_id = text(member.get("subject_id"))
            if not subject_id:
                continue
            previous = subjects.get(subject_id) or {}
            metrics = member.get("metrics") if isinstance(member.get("metrics"), dict) else {}
            rank_score = int(metrics.get("rank_score") or previous.get("rank_score") or 0)
            subjects[subject_id] = {
                "subject_id": subject_id,
                "subject_type": text(member.get("subject_type")) or text(previous.get("subject_type")),
                "display_name": text(member.get("display_name")) or text(previous.get("display_name")),
                "city_text": text(member.get("city_text")) or text(previous.get("city_text")),
                "taxon_path": text(member.get("taxon_path")) or text(previous.get("taxon_path")),
                "rank_score": rank_score,
            }
    return subjects, clusters


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


CITY_MARKERS = [
    "北京",
    "上海",
    "广州",
    "深圳",
    "杭州",
    "成都",
    "重庆",
    "南京",
    "昆明",
    "长沙",
    "武汉",
    "厦门",
    "西安",
    "香港",
]


def is_compound_entity_label(value: Any) -> bool:
    label = text(value)
    if not label:
        return False
    compact = label.replace(" ", "")
    city_hits = sum(1 for city in CITY_MARKERS if city in compact)
    if city_hits >= 2 and any(separator in compact for separator in (";", "；", "、", ",", "，", "/")):
        return True
    if "@" in compact and len(compact) > 4:
        return True
    lowered = label.casefold()
    if any(marker in lowered for marker in (" x ", "×", " x.", " b2b ")):
        return True
    if "+" in compact and len(compact) > 8:
        return True
    return False


def is_sound_system_entity_label(value: Any) -> bool:
    label = text(value).casefold()
    if not label:
        return False
    return any(
        marker in label
        for marker in (
            "soundsystem",
            "sound system",
            "音响系统",
            "sound-system",
        )
    )


def compound_labels_in_merge(decision: dict[str, Any], subjects: dict[str, dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    for subject_id in text_list(decision.get("merged_subject_ids")):
        label = subjects.get(subject_id, {}).get("display_name")
        if is_compound_entity_label(label):
            labels.append(text(label))
    return labels


def sound_system_labels_in_merge(decision: dict[str, Any], subjects: dict[str, dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    for subject_id in text_list(decision.get("merged_subject_ids")):
        label = subjects.get(subject_id, {}).get("display_name")
        if is_sound_system_entity_label(label):
            labels.append(text(label))
    return labels


def review_reason(decision: dict[str, Any], subjects: dict[str, dict[str, Any]], *, min_confidence: float) -> str:
    if text(decision.get("decision")) == "error":
        return "deepseek_error"
    if text(decision.get("decision")) != "merge":
        return text(decision.get("decision")) or "non_merge_decision"
    merged = text_list(decision.get("merged_subject_ids"))
    if len(merged) < 2:
        return "merge_without_multiple_members"
    missing = [subject_id for subject_id in merged if subject_id not in subjects]
    if missing:
        return "unknown_subject_in_merge"
    if sound_system_labels_in_merge(decision, subjects):
        return "sound_system_entity_label_blocked"
    if compound_labels_in_merge(decision, subjects):
        return "compound_multi_entity_label_blocked"
    try:
        confidence = float(decision.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < min_confidence:
        return "low_confidence"
    flags = set(text_list(decision.get("risk_flags")))
    if any(flag.startswith("llm_output_") for flag in flags):
        return "invalid_llm_output_flag"
    merged_types = {text(subjects[subject_id].get("subject_type")) for subject_id in merged}
    if "dj" in merged_types and len(merged_types) > 1:
        return "dj_non_dj_merge_blocked"
    non_dj_types = merged_types - {"dj"}
    if len(non_dj_types) > 1 and "mixed_type_merge" not in flags and confidence < 0.85:
        return "mixed_type_merge_needs_review"
    return ""


def choose_canonical(group_ids: list[str], decisions: list[dict[str, Any]], subjects: dict[str, dict[str, Any]]) -> str:
    votes = Counter(text(decision.get("canonical_subject_id")) for decision in decisions)
    group_set = set(group_ids)
    max_rank = max((int(subjects.get(subject_id, {}).get("rank_score") or 0) for subject_id in group_ids), default=0)

    def score(subject_id: str) -> tuple[float, int, str]:
        subject = subjects.get(subject_id, {})
        label = text(subject.get("display_name"))
        rank_score = int(subject.get("rank_score") or 0)
        if max_rank and rank_score < max_rank * 0.5:
            return (-1000000 + rank_score, rank_score, subject_id)
        vote_boost = int(votes.get(subject_id) or 0) * 25
        label_penalty = 0
        if is_compound_entity_label(label) or is_sound_system_entity_label(label):
            label_penalty += 100000
        if len(label) > 24:
            label_penalty += len(label)
        return (rank_score + vote_boost - label_penalty, rank_score, subject_id)

    return max((subject_id for subject_id in group_ids if subject_id in group_set), key=score)


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    queue_path = Path(args.queue)
    decisions_path = Path(args.decisions)
    out_dir = Path(args.out_dir)
    min_confidence = float(args.min_confidence)
    subjects, clusters = load_queue(queue_path)
    raw_decisions = read_jsonl(decisions_path) if decisions_path.exists() else []
    for extra_path in getattr(args, "extra_decisions", []) or []:
        path = Path(extra_path)
        if path.exists():
            raw_decisions.extend(read_jsonl(path))
    latest_by_cluster: dict[str, dict[str, Any]] = {}
    passthrough_without_cluster: list[dict[str, Any]] = []
    ignored_unknown_cluster_decisions = 0
    for row in raw_decisions:
        cluster_id = text(row.get("cluster_id"))
        if cluster_id:
            if cluster_id not in clusters:
                ignored_unknown_cluster_decisions += 1
                continue
            latest_by_cluster[cluster_id] = row
        else:
            passthrough_without_cluster.append(row)
    decisions = [*latest_by_cluster.values(), *passthrough_without_cluster]
    if bool(args.require_execute):
        decisions = [row for row in decisions if bool(row.get("execute"))]

    uf = UnionFind()
    accepted_decisions: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    split_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []
    counts = Counter()

    for decision in decisions:
        decision_name = text(decision.get("decision"))
        counts[f"decision:{decision_name or 'unknown'}"] += 1
        reason = review_reason(decision, subjects, min_confidence=min_confidence)
        if decision_name == "merge" and not reason:
            merged = text_list(decision.get("merged_subject_ids"))
            for subject_id in merged:
                uf.find(subject_id)
            for subject_id in merged[1:]:
                uf.union(merged[0], subject_id)
            accepted_decisions.append(decision)
        elif decision_name == "split":
            split_rows.append(decision)
        elif decision_name == "error":
            error_rows.append(decision)
            review_rows.append({**decision, "review_reason": reason})
        else:
            review_rows.append({**decision, "review_reason": reason or "review_decision"})

    group_ids_by_root: dict[str, list[str]] = defaultdict(list)
    for subject_id in uf.parent:
        group_ids_by_root[uf.find(subject_id)].append(subject_id)

    accepted_by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for decision in accepted_decisions:
        for subject_id in text_list(decision.get("merged_subject_ids")):
            accepted_by_subject[subject_id].append(decision)

    groups: list[dict[str, Any]] = []
    for ids in group_ids_by_root.values():
        group_ids = sorted(set(ids))
        if len(group_ids) < 2:
            continue
        source_decisions = []
        seen_cluster_ids: set[str] = set()
        for subject_id in group_ids:
            for decision in accepted_by_subject.get(subject_id, []):
                cluster_id = text(decision.get("cluster_id"))
                if cluster_id and cluster_id not in seen_cluster_ids:
                    seen_cluster_ids.add(cluster_id)
                    source_decisions.append(decision)
        canonical_id = choose_canonical(group_ids, source_decisions, subjects)
        confidences = []
        for decision in source_decisions:
            try:
                confidences.append(float(decision.get("confidence")))
            except (TypeError, ValueError):
                pass
        risk_flags = sorted({flag for decision in source_decisions for flag in text_list(decision.get("risk_flags"))})
        groups.append(
            {
                "schema_version": SCHEMA_VERSION + ".group",
                "group_id": f"entity-merge-group:{canonical_id}",
                "canonical_subject_id": canonical_id,
                "canonical_name": subjects.get(canonical_id, {}).get("display_name", canonical_id),
                "member_count": len(group_ids),
                "members": [
                    subjects.get(subject_id, {"subject_id": subject_id})
                    for subject_id in sorted(
                        group_ids,
                        key=lambda subject_id: (int(subjects.get(subject_id, {}).get("rank_score") or 0), subject_id),
                        reverse=True,
                    )
                ],
                "source_cluster_ids": sorted(seen_cluster_ids),
                "source_decision_count": len(source_decisions),
                "confidence_min": min(confidences) if confidences else 0.0,
                "confidence_avg": sum(confidences) / len(confidences) if confidences else 0.0,
                "risk_flags": risk_flags,
                "report_only": True,
            }
        )
    groups.sort(key=lambda row: (row["member_count"], row["confidence_avg"], row["canonical_name"]), reverse=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    groups_path = out_dir / "entity_merge_groups_report_only.jsonl"
    review_path = out_dir / "entity_merge_review_queue.jsonl"
    split_path = out_dir / "entity_merge_split_decisions.jsonl"
    errors_path = out_dir / "entity_merge_error_decisions.jsonl"
    write_jsonl(groups_path, groups)
    write_jsonl(review_path, review_rows)
    write_jsonl(split_path, split_rows)
    write_jsonl(errors_path, error_rows)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "atlas_entity_merge_plan_ready_report_only",
        "queue_path": str(queue_path),
        "decisions_path": str(decisions_path),
        "extra_decisions_paths": [str(Path(path)) for path in getattr(args, "extra_decisions", []) or []],
        "out_dir": str(out_dir),
        "min_confidence": min_confidence,
        "require_execute": bool(args.require_execute),
        "decisions_read": len(decisions),
        "raw_decisions_read": len(raw_decisions),
        "ignored_unknown_cluster_decisions": ignored_unknown_cluster_decisions,
        "superseded_decisions": len(raw_decisions) - ignored_unknown_cluster_decisions - len(decisions),
        "accepted_merge_decisions": len(accepted_decisions),
        "review_rows": len(review_rows),
        "split_rows": len(split_rows),
        "error_rows": len(error_rows),
        "merge_groups": len(groups),
        "merged_subjects": len({member["subject_id"] for group in groups for member in group["members"]}),
        "counts": dict(counts),
        "groups_path": str(groups_path),
        "review_path": str(review_path),
        "split_path": str(split_path),
        "errors_path": str(errors_path),
        "safety": {
            "report_only": True,
            "sqlite_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "production_pointer_updated": False,
        },
    }
    write_json(out_dir / "entity_merge_plan_summary.json", summary)
    write_markdown(out_dir / "entity_merge_plan_report.md", summary, groups[:30])
    return summary


def write_markdown(path: Path, summary: dict[str, Any], groups: list[dict[str, Any]]) -> None:
    lines = [
        "# Atlas Entity Merge Plan",
        "",
        f"- decision: `{summary['decision']}`",
        f"- decisions_read: `{summary['decisions_read']}`",
        f"- accepted_merge_decisions: `{summary['accepted_merge_decisions']}`",
        f"- review_rows: `{summary['review_rows']}`",
        f"- split_rows: `{summary['split_rows']}`",
        f"- merge_groups: `{summary['merge_groups']}`",
        f"- merged_subjects: `{summary['merged_subjects']}`",
        "",
        "## Top Merge Groups",
        "",
    ]
    for group in groups:
        labels = ", ".join(member.get("display_name") or member.get("subject_id") for member in group["members"][:12])
        lines.append(f"- `{group['canonical_name']}` / `{group['canonical_subject_id']}`: {group['member_count']} members; {labels}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", default=str(DEFAULT_QUEUE))
    parser.add_argument("--decisions", default=str(DEFAULT_DECISIONS))
    parser.add_argument("--extra-decisions", action="append", default=[])
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--min-confidence", type=float, default=0.72)
    parser.add_argument("--require-execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    summary = build_plan(parse_args(argv))
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
