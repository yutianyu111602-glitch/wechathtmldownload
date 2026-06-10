#!/usr/bin/env python3
"""Build a report-only GraphCandidatePack readiness packet for the atlas lane.

This P3-S1 gate records that the 47,340-row base graph marker is ready while
external identity/profile edges remain empty because the P2 review gate accepted
no direct identity proof.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_STABLE_MERGE = Path(
    "reports/stable_merge_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518/stable_merge_summary.json"
)
DEFAULT_PROMOTION_VERIFY = Path(
    "reports/graph_production_promotion_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_verify_20260518/promotion_report.json"
)
DEFAULT_REVIEW_GATE_SUMMARY = Path(
    "reports/external_identity_source_followup_review_gate_47k_delta375_20260519/source_followup_review_gate_summary.json"
)
DEFAULT_REVIEW_GATE_ROWS = Path(
    "reports/external_identity_source_followup_review_gate_47k_delta375_20260519/source_followup_review_gate.jsonl"
)
DEFAULT_ACCEPTED_EXTERNAL_EDGES = Path(
    "reports/external_identity_source_followup_review_gate_47k_delta375_20260519/accepted_external_identity_edges_for_graph.jsonl"
)
DEFAULT_OUT_DIR = Path("reports/graph_candidate_pack_readiness_47k_delta375_20260519")
SCHEMA_VERSION = "stage7_graph_candidate_pack_readiness.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for GraphCandidatePack readiness: {path}")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                value = json.loads(stripped)
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


def needs_more_source(row: dict[str, Any]) -> bool:
    decision = str(row.get("review_gate_decision") or "")
    return decision.startswith("needs_") or decision.startswith("candidate_")


def build_readiness(
    *,
    stable_merge_path: Path,
    promotion_verify_path: Path,
    review_gate_summary_path: Path,
    review_gate_rows_path: Path,
    accepted_external_edges_path: Path,
    out_dir: Path,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    stable = read_json(stable_merge_path)
    promotion = read_json(promotion_verify_path)
    review_summary = read_json(review_gate_summary_path)
    review_rows = read_jsonl(review_gate_rows_path)
    accepted_external_edges = read_jsonl(accepted_external_edges_path)
    source_recovery_rows = [row for row in review_rows if needs_more_source(row)]

    articles = int(stable.get("articles") or 0)
    graph_counts = (promotion.get("after_counts") or {})
    external_edge_count = len(accepted_external_edges)
    base_graph_ready = bool(promotion.get("ok")) and int((graph_counts.get("article") or {}).get("promoted") or 0) == articles
    external_identity_ready = external_edge_count > 0

    out_dir.mkdir(parents=True, exist_ok=True)
    external_edges_out = out_dir / "external_identity_edges_for_graphcandidatepack.jsonl"
    source_recovery_out = out_dir / "external_identity_needs_more_source_queue.jsonl"
    write_jsonl(external_edges_out, accepted_external_edges)
    write_jsonl(source_recovery_out, source_recovery_rows)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": base_graph_ready,
        "decision": "graph_candidate_pack_readiness_ready_external_identity_empty",
        "stable_merge_path": str(stable_merge_path),
        "promotion_verify_path": str(promotion_verify_path),
        "review_gate_summary_path": str(review_gate_summary_path),
        "review_gate_rows_path": str(review_gate_rows_path),
        "external_identity_edges_path": str(external_edges_out),
        "external_identity_needs_more_source_queue_path": str(source_recovery_out),
        "stable_articles": articles,
        "stable_totals": stable.get("totals") or {},
        "promotion_run_id": promotion.get("promotion_run_id"),
        "graph_counts": graph_counts,
        "base_graph_ready": base_graph_ready,
        "external_identity_reviewed_rows": int(review_summary.get("reviewed_rows") or 0),
        "external_identity_rejected_rows": int(review_summary.get("rejected_rows") or 0),
        "external_identity_needs_more_source_rows": len(source_recovery_rows),
        "external_identity_candidate_direct_text_rows": int(review_summary.get("candidate_direct_text_rows") or 0),
        "external_identity_edges": external_edge_count,
        "external_identity_ready": external_identity_ready,
        "graph_candidate_pack_base_ready": base_graph_ready,
        "graph_candidate_pack_external_identity_extension_ready": external_identity_ready,
        "next_gate": (
            "recover source context for needs-more-source rows before GraphCandidatePack profile edges"
            if not external_identity_ready
            else "run GraphCandidatePack dry-run import"
        ),
        "safety": {
            "report_only": True,
            "network_call_executed": False,
            "graph_write_executed": False,
            "qdrant_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
        },
    }
    write_json(out_dir / "graph_candidate_pack_readiness.json", summary)
    write_markdown(out_dir / "graph_candidate_pack_readiness.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# GraphCandidatePack Readiness",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- base_graph_ready: `{summary['base_graph_ready']}`",
        f"- stable_articles: `{summary['stable_articles']}`",
        f"- promotion_run_id: `{summary['promotion_run_id']}`",
        f"- external_identity_reviewed_rows: `{summary['external_identity_reviewed_rows']}`",
        f"- external_identity_rejected_rows: `{summary['external_identity_rejected_rows']}`",
        f"- external_identity_needs_more_source_rows: `{summary['external_identity_needs_more_source_rows']}`",
        f"- external_identity_candidate_direct_text_rows: `{summary['external_identity_candidate_direct_text_rows']}`",
        f"- external_identity_edges: `{summary['external_identity_edges']}`",
        f"- external_identity_edges_path: `{summary['external_identity_edges_path']}`",
        f"- external_identity_needs_more_source_queue_path: `{summary['external_identity_needs_more_source_queue_path']}`",
        f"- next_gate: `{summary['next_gate']}`",
        "",
        "## Graph Counts",
        "",
    ]
    for label, counts in sorted((summary.get("graph_counts") or {}).items()):
        lines.append(f"- `{label}`: `{counts}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only readiness packet.",
            "- No network calls.",
            "- No graph/vector/DB/mem0 writes.",
            "- External identity GraphCandidatePack edge output remains empty.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stable-merge", type=Path, default=DEFAULT_STABLE_MERGE)
    parser.add_argument("--promotion-verify", type=Path, default=DEFAULT_PROMOTION_VERIFY)
    parser.add_argument("--review-gate-summary", type=Path, default=DEFAULT_REVIEW_GATE_SUMMARY)
    parser.add_argument("--review-gate-rows", type=Path, default=DEFAULT_REVIEW_GATE_ROWS)
    parser.add_argument("--accepted-external-edges", type=Path, default=DEFAULT_ACCEPTED_EXTERNAL_EDGES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    summary = build_readiness(
        stable_merge_path=args.stable_merge,
        promotion_verify_path=args.promotion_verify,
        review_gate_summary_path=args.review_gate_summary,
        review_gate_rows_path=args.review_gate_rows,
        accepted_external_edges_path=args.accepted_external_edges,
        out_dir=args.out_dir,
    )
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "base_graph_ready": summary["base_graph_ready"],
                "external_identity_edges": summary["external_identity_edges"],
                "external_identity_needs_more_source_rows": summary["external_identity_needs_more_source_rows"],
                "summary": str(args.out_dir / "graph_candidate_pack_readiness.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if summary["ok"] else 2


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

