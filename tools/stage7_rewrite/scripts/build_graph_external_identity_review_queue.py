#!/usr/bin/env python3
"""Build report-only identity review queues from current external evidence.

Inputs are the HTTP-fast URL evidence and Maigret candidate-only evidence for
the current 47,340-row graph marker. Output rows are review tasks only. This
script never accepts identities and never writes graph/vector/DB stores.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_HTTP_RESULTS = Path("reports/graph_external_evidence_http_fast_47k_plus_paid_20260518/http_fast_results.jsonl")
DEFAULT_MAIGRET_EVIDENCE = Path(
    "reports/graph_maigret_canary_47k_plus_paid_20260518/maigret_normalized_candidate_evidence.jsonl"
)
DEFAULT_OUT_DIR = Path("reports/graph_external_identity_review_queue_47k_plus_paid_20260518")
SCHEMA_VERSION = "stage7_graph_external_identity_review_queue.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for identity review queue: {path}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    tmp.replace(path)


def normalize_http_row(row: dict[str, Any]) -> dict[str, Any] | None:
    decision = str(row.get("decision") or "")
    if decision != "public_url_reachable_review_ready":
        return None
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "source_family": "http_fast_url_evidence",
        "source_decision": decision,
        "review_tier": "source_url_reachable_identity_review",
        "seed_id": row.get("seed_id"),
        "source_article_uid": row.get("source_article_uid"),
        "source_account": row.get("source_account"),
        "source_title": row.get("source_title"),
        "url": row.get("url"),
        "final_url": row.get("final_url"),
        "status_code": row.get("status_code"),
        "content_type": row.get("content_type"),
        "identity_proof": False,
        "accepted_for_graph": False,
        "graph_write_allowed": False,
        "review_required": True,
        "review_reason": "Reachable public URL is source-backed evidence, but identity must be checked against article/entity context.",
        "next_action": "source_backed_identity_review",
    }


def normalize_maigret_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "source_family": "maigret_candidate_profile",
        "source_decision": row.get("confidence_cap") or "candidate_only_not_identity_proof",
        "review_tier": "maigret_candidate_identity_review",
        "username": row.get("username"),
        "site_name": row.get("site_name"),
        "url": row.get("url"),
        "status": row.get("status"),
        "tags": row.get("tags") or [],
        "source_status_path": row.get("source_status_path"),
        "report_path": row.get("report_path"),
        "identity_proof": False,
        "accepted_for_graph": False,
        "graph_write_allowed": False,
        "review_required": True,
        "review_reason": "Maigret hit is breadth evidence only and must be matched to source-backed entity context.",
        "next_action": "source_backed_identity_review",
    }


def build_review_queue(http_results: Path, maigret_evidence: Path, out_dir: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    http_rows = read_jsonl(http_results)
    maigret_rows = read_jsonl(maigret_evidence)
    normalized_http = [item for row in http_rows if (item := normalize_http_row(row))]
    normalized_maigret = [normalize_maigret_row(row) for row in maigret_rows]
    combined_rows = normalized_http + normalized_maigret
    family_counts = Counter(row["source_family"] for row in combined_rows)
    tier_counts = Counter(row["review_tier"] for row in combined_rows)

    out_dir.mkdir(parents=True, exist_ok=True)
    http_path = out_dir / "reachable_url_identity_review_queue.jsonl"
    maigret_path = out_dir / "maigret_identity_review_queue.jsonl"
    combined_path = out_dir / "external_identity_review_queue.jsonl"
    write_jsonl(http_path, normalized_http)
    write_jsonl(maigret_path, normalized_maigret)
    write_jsonl(combined_path, combined_rows)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "graph_external_identity_review_queue_ready",
        "http_results": str(http_results),
        "maigret_evidence": str(maigret_evidence),
        "reachable_url_review_path": str(http_path),
        "maigret_review_path": str(maigret_path),
        "combined_review_path": str(combined_path),
        "http_rows_seen": len(http_rows),
        "reachable_url_review_rows": len(normalized_http),
        "maigret_rows_seen": len(maigret_rows),
        "maigret_review_rows": len(normalized_maigret),
        "combined_review_rows": len(combined_rows),
        "family_counts": dict(family_counts),
        "tier_counts": dict(tier_counts),
        "accepted_for_graph": 0,
        "next_gate": "Review queue rows need direct/source-backed identity validation before GraphCandidatePack or graph writes.",
        "safety": {
            "accepted_for_graph": 0,
            "cookie_or_token_exported": False,
            "d_scan_executed": False,
            "graph_write_executed": False,
            "model_call_executed": False,
            "network_call_executed": False,
            "paid_api_used": False,
            "qdrant_write_executed": False,
            "report_only": True,
        },
    }
    write_json(out_dir / "external_identity_review_queue_summary.json", summary)
    write_markdown(out_dir / "external_identity_review_queue_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Graph External Identity Review Queue",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- http_rows_seen: `{summary['http_rows_seen']}`",
        f"- reachable_url_review_rows: `{summary['reachable_url_review_rows']}`",
        f"- maigret_rows_seen: `{summary['maigret_rows_seen']}`",
        f"- maigret_review_rows: `{summary['maigret_review_rows']}`",
        f"- combined_review_rows: `{summary['combined_review_rows']}`",
        f"- accepted_for_graph: `{summary['accepted_for_graph']}`",
        "",
        "## Output",
        "",
        f"- reachable URL queue: `{summary['reachable_url_review_path']}`",
        f"- Maigret queue: `{summary['maigret_review_path']}`",
        f"- combined queue: `{summary['combined_review_path']}`",
        "",
        "## Safety",
        "",
        "- Report-only queue builder.",
        "- No network calls.",
        "- No graph/vector/DB writes.",
        "- No paid API.",
        "- No D: scan.",
        "- No row is accepted for graph use by this script.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--http-results", type=Path, default=DEFAULT_HTTP_RESULTS)
    parser.add_argument("--maigret-evidence", type=Path, default=DEFAULT_MAIGRET_EVIDENCE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_review_queue(args.http_results, args.maigret_evidence, args.out_dir)
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "reachable_url_review_rows": summary["reachable_url_review_rows"],
                "maigret_review_rows": summary["maigret_review_rows"],
                "combined_review_rows": summary["combined_review_rows"],
                "summary": str(args.out_dir / "external_identity_review_queue_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
