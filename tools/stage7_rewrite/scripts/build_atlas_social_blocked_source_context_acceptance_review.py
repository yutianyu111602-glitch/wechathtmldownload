#!/usr/bin/env python3
"""Build report-only manual source-context acceptance for blocked Q6 entities.

This packet consumes the bounded local source-context follow-up output. It can
accept exact local Atlas source-context candidates for the next identity-review
gate, but it never promotes identity proof, avatar display, serving fields, or
graph writes.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_FOLLOWUP = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_blocked_source_context_followup_q6_20260525"
    / "atlas_social_blocked_source_context_followup.jsonl"
)
DEFAULT_CANDIDATES = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_blocked_source_context_followup_q6_20260525"
    / "atlas_social_blocked_source_context_candidates.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_blocked_source_context_acceptance_q6_20260525"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_BLOCKED_SOURCE_CONTEXT_ACCEPTANCE_REVIEW_20260525.md"
SCHEMA_VERSION = "stage7_atlas_social_blocked_source_context_acceptance_review.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Q6 source-context acceptance review: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def read_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    reject_d_path(path, label)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
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


def candidates_by_entity(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        entity_id = compact(row.get("entity_search_id"))
        if entity_id:
            result.setdefault(entity_id, []).append(row)
    return result


def unique_compact(rows: list[dict[str, Any]], field: str) -> list[str]:
    values = sorted({compact(row.get(field), 300) for row in rows if compact(row.get(field), 300)})
    return values


def build_review_row(
    *,
    followup: dict[str, Any],
    candidates: list[dict[str, Any]],
    generated_at: str,
    min_exact_candidates: int,
) -> dict[str, Any]:
    exact_candidates = [
        row
        for row in candidates
        if compact(row.get("match_kind")) == "exact_name_local_source_context_candidate"
    ]
    alias_candidates = [
        row
        for row in candidates
        if compact(row.get("match_kind")) == "alias_like_local_source_context_review"
    ]
    exact_sources = unique_compact(exact_candidates, "source_article_uid")
    exact_events = unique_compact(exact_candidates, "event_key")
    accepted = len(exact_candidates) >= min_exact_candidates and bool(exact_sources)

    if accepted:
        status = "manual_source_context_accepted_for_identity_review"
        reason = "Exact local source-context candidates exist in bounded Atlas sidecar evidence."
        next_gate = "Attach independent public profile evidence, then run a separate identity acceptance gate."
    elif alias_candidates:
        status = "manual_source_context_alias_only_still_blocked"
        reason = "Only alias-like local source-context candidates exist; exact source-context acceptance is blocked."
        next_gate = "Find exact local Atlas source context or stronger independent evidence before identity review."
    else:
        status = "manual_source_context_not_found_still_blocked"
        reason = "No local source-context candidates were available for manual acceptance."
        next_gate = "Continue bounded source-context search before identity review."

    return {
        "schema_version": SCHEMA_VERSION + ".entity",
        "generated_at": generated_at,
        "entity_search_id": compact(followup.get("entity_search_id")),
        "name": compact(followup.get("name")),
        "type": compact(followup.get("type")),
        "previous_followup_status": compact(followup.get("followup_status")),
        "exact_candidate_count": len(exact_candidates),
        "alias_like_candidate_count": len(alias_candidates),
        "selected_context_candidate_count": len(candidates),
        "exact_source_article_count": len(exact_sources),
        "exact_event_count": len(exact_events),
        "accepted_source_articles": exact_sources,
        "accepted_event_keys": exact_events,
        "manual_source_context_decision": status,
        "review_reason": reason,
        "next_gate": next_gate,
        "accepted_for_graph": False,
        "identity_proof": False,
        "identity_proof_promoted": False,
        "avatar_display_allowed": False,
        "public_serving_field_allowed": False,
        "graph_write_allowed": False,
    }


def build_acceptance_review(
    *,
    followup_path: Path,
    candidates_path: Path,
    out_dir: Path,
    report_path: Path,
    min_exact_candidates: int,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    generated_at = now_iso()
    followup_rows = read_jsonl(followup_path, "followup")
    candidate_rows = read_jsonl(candidates_path, "candidates")
    candidate_lookup = candidates_by_entity(candidate_rows)

    review_rows = [
        build_review_row(
            followup=row,
            candidates=candidate_lookup.get(compact(row.get("entity_search_id")), []),
            generated_at=generated_at,
            min_exact_candidates=min_exact_candidates,
        )
        for row in followup_rows
    ]
    accepted_rows = [
        row
        for row in review_rows
        if row["manual_source_context_decision"] == "manual_source_context_accepted_for_identity_review"
    ]
    blocked_rows = [
        row
        for row in review_rows
        if row["manual_source_context_decision"] != "manual_source_context_accepted_for_identity_review"
    ]
    decision_counts = Counter(row["manual_source_context_decision"] for row in review_rows)

    review_path = out_dir / "atlas_social_blocked_source_context_acceptance_review.jsonl"
    accepted_path = out_dir / "atlas_social_blocked_source_context_acceptance_ready.jsonl"
    blocked_path = out_dir / "atlas_social_blocked_source_context_acceptance_remaining_blocked.jsonl"
    summary_path = out_dir / "atlas_social_blocked_source_context_acceptance_summary.json"
    write_jsonl(review_path, review_rows)
    write_jsonl(accepted_path, accepted_rows)
    write_jsonl(blocked_path, blocked_rows)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "ok": True,
        "decision": (
            "atlas_social_blocked_source_context_acceptance_ready_report_only"
            if accepted_rows
            else "atlas_social_blocked_source_context_acceptance_blocked_report_only"
        ),
        "followup_path": str(followup_path),
        "candidates_path": str(candidates_path),
        "out_dir": str(out_dir),
        "report_path": str(report_path),
        "review_path": str(review_path),
        "accepted_path": str(accepted_path),
        "blocked_path": str(blocked_path),
        "entity_rows": len(review_rows),
        "candidate_rows": len(candidate_rows),
        "manual_source_context_accepted": len(accepted_rows),
        "remaining_blocked_rows": len(blocked_rows),
        "accepted_entities": [row["name"] for row in accepted_rows],
        "remaining_blocked_entities": [row["name"] for row in blocked_rows],
        "decision_counts": dict(sorted(decision_counts.items())),
        "accepted_for_graph": 0,
        "identity_proof_promoted": 0,
        "avatar_display_allowed": 0,
        "public_serving_field_allowed": 0,
        "graph_write_allowed": 0,
        "next_gate": "Accepted source-context rows still need independent public profile evidence and a separate identity acceptance gate before any product/public/graph use.",
        "safety": {
            "report_only": True,
            "network_call_executed": False,
            "model_call_executed": False,
            "paid_api_used": False,
            "graph_write_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_or_agentmemory_write_executed": False,
            "secret_value_read_or_printed": False,
            "d_scan_executed": False,
        },
    }
    write_json(summary_path, summary)
    write_markdown(out_dir / "atlas_social_blocked_source_context_acceptance_summary.md", summary, review_rows)
    write_markdown(report_path, summary, review_rows, top_level=True)
    return summary


def write_markdown(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]], top_level: bool = False) -> None:
    title = "Atlas T6 Blocked Source-Context Acceptance Review Packet" if top_level else "Atlas Source-Context Acceptance Review"
    lines = [
        f"# {title}",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- entity_rows: `{summary['entity_rows']}`",
        f"- candidate_rows: `{summary['candidate_rows']}`",
        f"- manual_source_context_accepted: `{summary['manual_source_context_accepted']}`",
        f"- remaining_blocked_rows: `{summary['remaining_blocked_rows']}`",
        f"- accepted_for_graph: `{summary['accepted_for_graph']}`",
        f"- identity_proof_promoted: `{summary['identity_proof_promoted']}`",
        f"- avatar_display_allowed: `{summary['avatar_display_allowed']}`",
        f"- public_serving_field_allowed: `{summary['public_serving_field_allowed']}`",
        f"- graph_write_allowed: `{summary['graph_write_allowed']}`",
        f"- review_path: `{summary['review_path']}`",
        f"- accepted_path: `{summary['accepted_path']}`",
        f"- blocked_path: `{summary['blocked_path']}`",
        "",
        "## Entity Decisions",
        "",
        "| entity | decision | exact candidates | exact sources | next gate |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            "| {name} | {decision} | {exact} | {sources} | {next_gate} |".format(
                name=row["name"],
                decision=row["manual_source_context_decision"],
                exact=row["exact_candidate_count"],
                sources=row["exact_source_article_count"],
                next_gate=row["next_gate"],
            )
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Report-only manual source-context review.",
            "- No identity proof, avatar display permission, public serving field, graph write, Neo4j/Qdrant/SQLite write, public pointer, deploy, upload/review, memory write, network/model/paid API, credential read, destructive Git, 9router use, or D: root scan was executed.",
            f"- Next gate: {summary['next_gate']}",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--followup", type=Path, default=DEFAULT_FOLLOWUP)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--min-exact-candidates", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_acceptance_review(
        followup_path=args.followup,
        candidates_path=args.candidates,
        out_dir=args.out_dir,
        report_path=args.report,
        min_exact_candidates=args.min_exact_candidates,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "summary": str(args.out_dir / "atlas_social_blocked_source_context_acceptance_summary.json"),
                "report": str(args.report),
                "manual_source_context_accepted": summary["manual_source_context_accepted"],
                "remaining_blocked_rows": summary["remaining_blocked_rows"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
