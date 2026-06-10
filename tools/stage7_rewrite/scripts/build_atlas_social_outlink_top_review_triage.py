#!/usr/bin/env python3
"""Build a report-only triage packet from the Q6 top-review outlink queue.

This narrows the 80-row review queue into a bounded content-fetch plan without
fetching pages or promoting graph truth.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


STAGE7_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOP_QUEUE = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_outlink_followup_review_q6_20260523_2019"
    / "atlas_social_outlink_followup_top_review_queue.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_outlink_top_review_triage_q6_20260523"
SCHEMA_VERSION = "stage7_atlas_social_outlink_top_review_triage.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Q6 triage: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            if line.strip():
                item = json.loads(line)
                if isinstance(item, dict):
                    rows.append(item)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        compact(row.get("entity_search_id")),
        compact(row.get("profile_url"), 3000).casefold(),
        compact(row.get("outlink_url"), 3000).casefold(),
    )


def classify_next_step(row: dict[str, Any]) -> tuple[str, list[str], int]:
    decision = compact(row.get("review_decision"))
    score = int(row.get("review_score") or 0)
    reasons = row.get("decision_reasons") if isinstance(row.get("decision_reasons"), list) else []
    outlink_kind = compact(row.get("outlink_kind"))
    platform = compact(row.get("outlink_platform"))
    explanation: list[str] = []

    if decision == "manual_review_direct_profile_candidate" and score >= 80:
        explanation.extend(["direct_profile_candidate", f"platform:{platform}", f"kind:{outlink_kind}"])
        return "bounded_fetch_profile_page_candidate", explanation, score + 20
    if decision == "manual_review_music_artifact_candidate" and score >= 90 and "subject_match" in reasons:
        explanation.extend(["subject_matched_music_artifact", f"platform:{platform}", f"kind:{outlink_kind}"])
        return "bounded_fetch_music_artifact_candidate", explanation, score + 5
    if decision == "manual_review_subject_matched_candidate" and score >= 80:
        explanation.extend(["subject_matched_secondary_candidate", f"platform:{platform}"])
        return "hold_for_manual_review_before_fetch", explanation, score
    explanation.append("insufficient_priority_for_next_fetch_slice")
    return "defer_from_next_fetch_slice", explanation, max(score - 10, 0)


def triage_row(row: dict[str, Any], rank: int) -> dict[str, Any]:
    next_step, reasons, score = classify_next_step(row)
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "triaged_at": now_iso(),
        "triage_rank": rank,
        "triage_score": score,
        "next_step": next_step,
        "next_step_reasons": reasons,
        "entity_search_id": compact(row.get("entity_search_id")),
        "name": compact(row.get("name")),
        "type": compact(row.get("type")),
        "review_decision": compact(row.get("review_decision")),
        "review_score": row.get("review_score"),
        "outlink_platform": compact(row.get("outlink_platform")),
        "outlink_kind": compact(row.get("outlink_kind")),
        "outlink_url": compact(row.get("outlink_url"), 3000),
        "anchor_text": compact(row.get("anchor_text"), 500),
        "profile_url": compact(row.get("profile_url"), 3000),
        "content_fetch_allowed_next": next_step.startswith("bounded_fetch_"),
        "accepted_for_graph": False,
        "identity_proof": False,
        "graph_write_allowed": False,
    }


def build_triage_packet(*, top_queue_path: Path, out_dir: Path, max_fetch_rows: int) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    rows = read_jsonl(top_queue_path)
    seen: set[tuple[str, str, str]] = set()
    triaged: list[dict[str, Any]] = []
    for row in rows:
        key = row_key(row)
        if key in seen:
            continue
        seen.add(key)
        triaged.append(triage_row(row, len(triaged) + 1))
    triaged.sort(
        key=lambda item: (
            bool(item["content_fetch_allowed_next"]),
            int(item["triage_score"] or 0),
            compact(item.get("name")),
        ),
        reverse=True,
    )
    for index, row in enumerate(triaged, start=1):
        row["triage_rank"] = index

    fetch_rows = [row for row in triaged if row["content_fetch_allowed_next"]][: max(max_fetch_rows, 0)]
    deferred_rows = [row for row in triaged if row not in fetch_rows]

    fetch_path = out_dir / "atlas_social_outlink_bounded_fetch_plan.jsonl"
    deferred_path = out_dir / "atlas_social_outlink_deferred_review_rows.jsonl"
    write_jsonl(fetch_path, fetch_rows)
    write_jsonl(deferred_path, deferred_rows)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "atlas_social_outlink_top_review_triage_ready_report_only",
        "top_queue_path": str(top_queue_path),
        "fetch_plan_path": str(fetch_path),
        "deferred_rows_path": str(deferred_path),
        "input_rows": len(rows),
        "deduped_rows": len(triaged),
        "selected_fetch_rows": len(fetch_rows),
        "deferred_rows": len(deferred_rows),
        "next_step_counts": dict(Counter(row["next_step"] for row in triaged)),
        "platform_counts": dict(Counter(row["outlink_platform"] for row in triaged)),
        "accepted_for_graph": 0,
        "identity_proof_promoted": 0,
        "graph_write_allowed": 0,
        "content_fetch_executed": False,
        "content_fetch_justified": bool(fetch_rows),
        "safety": {
            "report_only": True,
            "network_call_executed": False,
            "model_call_executed": False,
            "paid_api_used": False,
            "graph_write_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "secret_value_read_or_printed": False,
            "d_scan_executed": False,
        },
    }
    write_json(out_dir / "atlas_social_outlink_top_review_triage_summary.json", summary)
    write_markdown(out_dir / "atlas_social_outlink_top_review_triage_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Atlas Social Outlink Top-Review Triage",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- input_rows: `{summary['input_rows']}`",
        f"- deduped_rows: `{summary['deduped_rows']}`",
        f"- selected_fetch_rows: `{summary['selected_fetch_rows']}`",
        f"- deferred_rows: `{summary['deferred_rows']}`",
        f"- content_fetch_justified: `{summary['content_fetch_justified']}`",
        f"- content_fetch_executed: `{summary['content_fetch_executed']}`",
        f"- accepted_for_graph: `{summary['accepted_for_graph']}`",
        f"- identity_proof_promoted: `{summary['identity_proof_promoted']}`",
        f"- graph_write_allowed: `{summary['graph_write_allowed']}`",
        f"- fetch_plan_path: `{summary['fetch_plan_path']}`",
        f"- deferred_rows_path: `{summary['deferred_rows_path']}`",
        "",
        "## Next Step Counts",
        "",
    ]
    for key, value in sorted(summary["next_step_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Platform Counts", ""])
    for key, value in sorted(summary["platform_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only triage; no content fetch was executed.",
            "- Accepted graph edge output remains empty by design.",
            "- Use the fetch plan only as a bounded candidate queue for the next T6 pass.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-queue", type=Path, default=DEFAULT_TOP_QUEUE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--max-fetch-rows", type=int, default=24)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_triage_packet(
        top_queue_path=args.top_queue,
        out_dir=args.out_dir,
        max_fetch_rows=args.max_fetch_rows,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
