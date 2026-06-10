#!/usr/bin/env python3
"""Build report-only T5/T7 acceptance gate for Atlas social identity candidates.

The input rows already have local Atlas source-context review. This gate only
separates rows that are ready for manual independent-profile review from rows
that still lack Atlas context. It never promotes identity proof or graph writes.
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
DEFAULT_SOURCE_REVIEW = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_identity_source_context_review_q6_20260524_0124"
    / "atlas_social_identity_source_context_review.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_identity_acceptance_gate_q6_20260524"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_IDENTITY_ACCEPTANCE_GATE_PACKET_20260524.md"
SCHEMA_VERSION = "stage7_atlas_social_identity_acceptance_gate.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Q6 identity acceptance gate: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "source_review")
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


def classify(row: dict[str, Any]) -> tuple[str, str, list[str]]:
    review_status = compact(row.get("review_status"))
    common_requirements = [
        "independent rendered public profile evidence or public profile body",
        "profile/avatar evidence hash from a supported public evidence runner",
        "cross-domain subject match between Atlas entity and external profile",
        "explicit T5/T7 acceptance decision for this entity and profile URL",
        "separate graph/write gate before Neo4j/Qdrant/serving mutation",
    ]
    if review_status == "atlas_source_context_found_manual_identity_review_needed":
        return (
            "manual_acceptance_review_ready_without_identity_proof",
            "T5/T7 can review independent profile evidence for this entity; do not promote yet.",
            common_requirements,
        )
    if review_status == "atlas_profile_found_needs_event_source_context":
        return (
            "blocked_needs_atlas_event_source_context",
            "Find Atlas event/source context before identity acceptance review.",
            ["Atlas event/source context for this entity", *common_requirements],
        )
    return (
        "blocked_needs_atlas_source_context",
        "Find local Atlas source context before identity acceptance review.",
        ["local Atlas profile/event/source context for this entity", *common_requirements],
    )


def build_gate_row(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    gate_status, next_action, requirements = classify(row)
    return {
        "schema_version": SCHEMA_VERSION + ".entity",
        "generated_at": generated_at,
        "review_rank": int(row.get("review_rank") or 0),
        "entity_search_id": compact(row.get("entity_search_id")),
        "name": compact(row.get("name")),
        "type": compact(row.get("type")),
        "atlas_dj_id": compact(row.get("atlas_dj_id")),
        "atlas_display_name": compact(row.get("atlas_display_name")),
        "atlas_profile_found": bool(row.get("atlas_profile_found")),
        "atlas_event_count": int(row.get("atlas_event_count") or 0),
        "atlas_source_article_count": int(row.get("atlas_source_article_count") or 0),
        "profile_identity_candidate_rows": int(row.get("profile_identity_candidate_rows") or 0),
        "supporting_music_artifact_rows": int(row.get("supporting_music_artifact_rows") or 0),
        "source_review_status": compact(row.get("review_status")),
        "acceptance_gate_status": gate_status,
        "acceptance_requirements": requirements,
        "next_action": next_action,
        "accepted_for_graph": False,
        "identity_proof": False,
        "identity_proof_promoted": False,
        "avatar_display_allowed": False,
        "public_serving_field_allowed": False,
        "graph_write_allowed": False,
    }


def build_acceptance_gate(*, source_review_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    generated_at = now_iso()
    source_rows = read_jsonl(source_review_path)
    gate_rows = [build_gate_row(row, generated_at) for row in source_rows]
    ready_rows = [
        row
        for row in gate_rows
        if row["acceptance_gate_status"] == "manual_acceptance_review_ready_without_identity_proof"
    ]
    blocked_rows = [
        row
        for row in gate_rows
        if row["acceptance_gate_status"] != "manual_acceptance_review_ready_without_identity_proof"
    ]

    gate_path = out_dir / "atlas_social_identity_acceptance_gate.jsonl"
    manual_review_path = out_dir / "atlas_social_identity_manual_acceptance_review_queue.jsonl"
    blocked_path = out_dir / "atlas_social_identity_acceptance_blocked.jsonl"
    summary_path = out_dir / "atlas_social_identity_acceptance_gate_summary.json"
    write_jsonl(gate_path, gate_rows)
    write_jsonl(manual_review_path, ready_rows)
    write_jsonl(blocked_path, blocked_rows)

    status_counts = Counter(row["acceptance_gate_status"] for row in gate_rows)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "ok": True,
        "decision": "atlas_social_identity_acceptance_gate_ready_report_only",
        "source_review_path": str(source_review_path),
        "out_dir": str(out_dir),
        "report_path": str(report_path),
        "gate_path": str(gate_path),
        "manual_review_path": str(manual_review_path),
        "blocked_path": str(blocked_path),
        "entity_rows": len(gate_rows),
        "manual_acceptance_review_ready": len(ready_rows),
        "blocked_rows": len(blocked_rows),
        "status_counts": dict(sorted(status_counts.items())),
        "accepted_for_graph": 0,
        "identity_proof_promoted": 0,
        "avatar_display_allowed": 0,
        "public_serving_field_allowed": 0,
        "graph_write_allowed": 0,
        "next_gate": "T5/T7 must attach independent rendered public profile evidence before any product truth, avatar display, serving field, graph/vector/DB write, or memory action.",
        "safety": {
            "report_only": True,
            "network_call_executed": False,
            "model_call_executed": False,
            "paid_api_used": False,
            "page_body_persisted": False,
            "graph_write_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "secret_value_read_or_printed": False,
            "d_scan_executed": False,
        },
    }
    write_json(summary_path, summary)
    write_markdown(out_dir / "atlas_social_identity_acceptance_gate_summary.md", summary, gate_rows)
    write_markdown(report_path, summary, gate_rows, top_level=True)
    return summary


def write_markdown(path: Path, summary: dict[str, Any], gate_rows: list[dict[str, Any]], top_level: bool = False) -> None:
    title = "Atlas T6 Identity Acceptance Gate Packet" if top_level else "Atlas Social Identity Acceptance Gate"
    lines = [
        f"# {title}",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- entity_rows: `{summary['entity_rows']}`",
        f"- manual_acceptance_review_ready: `{summary['manual_acceptance_review_ready']}`",
        f"- blocked_rows: `{summary['blocked_rows']}`",
        f"- accepted_for_graph: `{summary['accepted_for_graph']}`",
        f"- identity_proof_promoted: `{summary['identity_proof_promoted']}`",
        f"- avatar_display_allowed: `{summary['avatar_display_allowed']}`",
        f"- public_serving_field_allowed: `{summary['public_serving_field_allowed']}`",
        f"- graph_write_allowed: `{summary['graph_write_allowed']}`",
        f"- gate_path: `{summary['gate_path']}`",
        f"- manual_review_path: `{summary['manual_review_path']}`",
        f"- blocked_path: `{summary['blocked_path']}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in summary["status_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Entity Gate Rows", ""])
    for row in gate_rows:
        lines.append(
            "- `{name}` `{entity}`: gate `{gate}`, source_status `{source}`, atlas_events `{events}`, source_articles `{articles}`".format(
                name=row["name"],
                entity=row["entity_search_id"],
                gate=row["acceptance_gate_status"],
                source=row["source_review_status"],
                events=row["atlas_event_count"],
                articles=row["atlas_source_article_count"],
            )
        )
    lines.extend(
        [
            "",
            "## Manual Gate",
            "",
            "- Ready rows are ready only for manual independent-profile evidence review.",
            "- Ready rows are not identity proof, not avatar permission, and not graph/write permission.",
            "- Blocked rows need Atlas source context before profile identity acceptance review.",
            "",
            "## Safety",
            "",
        ]
    )
    for key, value in sorted(summary["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", f"- Next gate: {summary['next_gate']}", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-review", type=Path, default=DEFAULT_SOURCE_REVIEW)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_acceptance_gate(
        source_review_path=args.source_review,
        out_dir=args.out_dir,
        report_path=args.report_path,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "entity_rows": summary["entity_rows"],
                "manual_acceptance_review_ready": summary["manual_acceptance_review_ready"],
                "blocked_rows": summary["blocked_rows"],
                "accepted_for_graph": summary["accepted_for_graph"],
                "summary": str(args.out_dir / "atlas_social_identity_acceptance_gate_summary.json"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
