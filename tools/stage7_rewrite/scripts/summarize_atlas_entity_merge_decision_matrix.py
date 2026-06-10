#!/usr/bin/env python3
"""Summarize Atlas entity-merge DeepSeek decision matrix outputs."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PRO = REPO_ROOT / "reports" / "atlas_entity_merge_second_pass_matrix_pro_subset_current" / "entity_merge_llm_decisions.jsonl"
DEFAULT_FLASH = REPO_ROOT / "reports" / "atlas_entity_merge_second_pass_matrix_flash_subset_current" / "entity_merge_llm_decisions.jsonl"
DEFAULT_PRO_STRICT = REPO_ROOT / "reports" / "atlas_entity_merge_second_pass_matrix_pro_strict_current" / "entity_merge_llm_decisions.jsonl"
DEFAULT_FLASH_SOUND = REPO_ROOT / "reports" / "atlas_entity_merge_second_pass_matrix_flash_sound_current" / "entity_merge_llm_decisions.jsonl"
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_entity_merge_decision_matrix_secondpass_current"
SCHEMA_VERSION = "atlas_entity_merge_decision_matrix_summary.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def text(value: Any) -> str:
    return str(value or "").strip()


def load_queue_ids(path: Path | None) -> set[str]:
    if not path:
        return set()
    return {text(row.get("cluster_id")) for row in read_jsonl(path) if text(row.get("cluster_id"))}


def summarize_file(label: str, path: Path, allowed_cluster_ids: set[str] | None = None) -> dict[str, Any]:
    rows = read_jsonl(path)
    latest: dict[str, dict[str, Any]] = {}
    duplicate_rows = 0
    out_of_scope_rows = 0
    for row in rows:
        cluster_id = text(row.get("cluster_id"))
        if not cluster_id:
            continue
        if allowed_cluster_ids is not None and cluster_id not in allowed_cluster_ids:
            out_of_scope_rows += 1
            continue
        if cluster_id in latest:
            duplicate_rows += 1
        latest[cluster_id] = row
    decision_counts = Counter(text(row.get("decision")) or "unknown" for row in latest.values())
    raw_decision_counts = Counter(text(row.get("decision")) or "unknown" for row in rows)
    return {
        "label": label,
        "path": str(path),
        "raw_rows": len(rows),
        "unique_clusters": len(latest),
        "duplicate_cluster_rows": duplicate_rows,
        "out_of_scope_rows": out_of_scope_rows,
        "decision_counts": dict(sorted(decision_counts.items())),
        "raw_decision_counts": dict(sorted(raw_decision_counts.items())),
        "latest_by_cluster": latest,
    }


def compare_to_base(base: dict[str, Any], other: dict[str, Any], sample_limit: int) -> dict[str, Any]:
    base_latest: dict[str, dict[str, Any]] = base["latest_by_cluster"]
    other_latest: dict[str, dict[str, Any]] = other["latest_by_cluster"]
    common_ids = sorted(set(base_latest) & set(other_latest))
    conflicts: list[dict[str, Any]] = []
    pairs = Counter()
    for cluster_id in common_ids:
        base_decision = text(base_latest[cluster_id].get("decision")) or "unknown"
        other_decision = text(other_latest[cluster_id].get("decision")) or "unknown"
        pairs[f"{base_decision}->{other_decision}"] += 1
        if base_decision != other_decision:
            conflicts.append(
                {
                    "cluster_id": cluster_id,
                    "base_decision": base_decision,
                    "other_decision": other_decision,
                    "base_confidence": base_latest[cluster_id].get("confidence"),
                    "other_confidence": other_latest[cluster_id].get("confidence"),
                    "base_risk_flags": base_latest[cluster_id].get("risk_flags") or [],
                    "other_risk_flags": other_latest[cluster_id].get("risk_flags") or [],
                    "base_reason": base_latest[cluster_id].get("rationale") or base_latest[cluster_id].get("reason") or "",
                    "other_reason": other_latest[cluster_id].get("rationale") or other_latest[cluster_id].get("reason") or "",
                }
            )
    return {
        "base_label": base["label"],
        "other_label": other["label"],
        "base_unique_clusters": base["unique_clusters"],
        "other_unique_clusters": other["unique_clusters"],
        "common_clusters": len(common_ids),
        "base_only_clusters": len(set(base_latest) - set(other_latest)),
        "other_only_clusters": len(set(other_latest) - set(base_latest)),
        "decision_pair_counts": dict(sorted(pairs.items())),
        "conflict_count": len(conflicts),
        "conflict_samples": conflicts[:sample_limit],
    }


def strip_latest(summary: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in summary.items() if key != "latest_by_cluster"}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Atlas Entity Merge Decision Matrix",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        "- accepted route: `deepseek-v4-pro custom second-pass prompt`",
        "- rejected as direct merge source: `deepseek-v4-flash` matrix outputs",
        "",
        "## Inputs",
        "",
    ]
    for item in summary["inputs"].values():
        lines.append(
            f"- `{item['label']}`: `{item['unique_clusters']}` unique clusters, raw rows `{item['raw_rows']}`, decisions `{item['decision_counts']}`"
        )
    lines.extend(["", "## Comparisons", ""])
    for comparison in summary["comparisons"]:
        lines.append(
            f"- `{comparison['base_label']}` vs `{comparison['other_label']}`: common `{comparison['common_clusters']}`, "
            f"conflicts `{comparison['conflict_count']}`, pairs `{comparison['decision_pair_counts']}`"
        )
        for sample in comparison["conflict_samples"][:8]:
            lines.append(f"  - `{sample['cluster_id']}`: `{sample['base_decision']}` -> `{sample['other_decision']}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This is report-only matrix analysis.",
            "- No DeepSeek call, SQLite write, Neo4j write, Qdrant write, mem0 write, or production pointer update.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = Path(args.out_dir)
    queue_path = Path(args.queue) if text(getattr(args, "queue", "")) else None
    allowed_cluster_ids = load_queue_ids(queue_path) if queue_path else None
    inputs = {
        "pro": summarize_file("pro_custom", Path(args.pro), allowed_cluster_ids),
        "flash": summarize_file("flash_custom", Path(args.flash), allowed_cluster_ids),
        "pro_strict": summarize_file("pro_strict", Path(args.pro_strict), allowed_cluster_ids),
        "flash_sound": summarize_file("flash_sound_aware", Path(args.flash_sound), allowed_cluster_ids),
    }
    comparisons = [
        compare_to_base(inputs["pro"], inputs["flash"], int(args.sample_limit)),
        compare_to_base(inputs["pro"], inputs["pro_strict"], int(args.sample_limit)),
        compare_to_base(inputs["pro"], inputs["flash_sound"], int(args.sample_limit)),
    ]
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "atlas_entity_merge_decision_matrix_ready_report_only",
        "queue_filter": {
            "queue_path": str(queue_path) if queue_path else "",
            "cluster_count": len(allowed_cluster_ids) if allowed_cluster_ids is not None else 0,
        },
        "inputs": {key: strip_latest(value) for key, value in inputs.items()},
        "comparisons": comparisons,
        "recommendation": {
            "final_acceptance_decisions": str(Path(args.pro)),
            "do_not_accept_directly": [str(Path(args.flash)), str(Path(args.flash_sound))],
            "review_only": [str(Path(args.pro_strict))],
            "reason": "Flash is materially more aggressive on ambiguous venue/organizer/sound-system clusters; Pro custom has the best strictness/coverage balance.",
        },
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
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "entity_merge_decision_matrix_summary.json", summary)
    write_markdown(out_dir / "entity_merge_decision_matrix_report.md", summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pro", default=str(DEFAULT_PRO))
    parser.add_argument("--flash", default=str(DEFAULT_FLASH))
    parser.add_argument("--pro-strict", default=str(DEFAULT_PRO_STRICT))
    parser.add_argument("--flash-sound", default=str(DEFAULT_FLASH_SOUND))
    parser.add_argument("--queue", default="")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--sample-limit", type=int, default=20)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    summary = run(parse_args(argv))
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
