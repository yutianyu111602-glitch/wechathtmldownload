#!/usr/bin/env python3
"""Build the Atlas five-tool Phase 1 identity review queue.

This combines Phase 1 HTTP-fast metadata, OpenCLI profile metadata, and optional
Maigret normalized evidence into one strict review queue. It never accepts graph
edges and never writes graph/vector/database state.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_SEED_QUEUE = Path("reports/atlas_open_source_stack_phase1_16_20260521/external_evidence_seed_queue.jsonl")
DEFAULT_HTTP_RESULTS = Path("reports/atlas_open_source_stack_phase1_http_fast_16_20260521/http_fast_results.jsonl")
DEFAULT_OPENCLI_EVIDENCE = Path("reports/atlas_open_source_stack_phase1_opencli_live_8_20260521/social_profile_evidence.jsonl")
DEFAULT_MAIGRET_EVIDENCE = Path("reports/atlas_open_source_stack_phase1_maigret_normalized_16_20260521/maigret_normalized_candidate_evidence.jsonl")
DEFAULT_OUT_DIR = Path("reports/atlas_open_source_stack_phase1_review_queue_16_20260521")
SCHEMA_VERSION = "stage7_atlas_open_source_phase1_review_queue.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_broad_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"}:
        raise ValueError(f"{label} refuses broad D root: {path}")
    if raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses banned D subtree: {path}")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_url(value: str) -> str:
    raw = first_text(value)
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw.casefold()
    host = parsed.netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme.casefold()}://{host}{path}".casefold()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_broad_d_path(path, "jsonl")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
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


def seed_indexes(seed_rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id = {first_text(row.get("seed_id")): row for row in seed_rows if first_text(row.get("seed_id"))}
    by_url: dict[str, dict[str, Any]] = {}
    for row in seed_rows:
        if row.get("seed_family") != "url_evidence":
            continue
        for key in (row.get("url"), row.get("final_url")):
            normalized = normalize_url(first_text(key))
            if normalized and normalized not in by_url:
                by_url[normalized] = row
    return by_id, by_url


def seed_for_url(url_seed_index: dict[str, dict[str, Any]], *urls: Any) -> dict[str, Any]:
    for value in urls:
        normalized = normalize_url(first_text(value))
        if normalized in url_seed_index:
            return url_seed_index[normalized]
    return {}


def normalize_http_row(row: dict[str, Any]) -> dict[str, Any] | None:
    if first_text(row.get("decision")) != "public_url_reachable_review_ready":
        return None
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "source_family": "http_fast_url_evidence",
        "source_decision": first_text(row.get("decision")),
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
        "review_reason": "Reachable public URL still needs direct/source-backed identity review.",
        "next_action": "source_backed_identity_review",
    }


def normalize_opencli_row(row: dict[str, Any], url_seed_index: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if first_text(row.get("decision")) != "report_ready":
        return None
    seed = seed_for_url(
        url_seed_index,
        row.get("input_url"),
        row.get("canonical_url"),
        row.get("final_url"),
        row.get("evidence_url"),
    )
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "source_family": "opencli_profile_metadata",
        "source_decision": first_text(row.get("decision")),
        "review_tier": "opencli_profile_content_identity_review",
        "seed_id": seed.get("seed_id"),
        "subject_name": first_text(row.get("subject_name")),
        "source_article_uid": seed.get("source_article_uid"),
        "source_account": seed.get("source_account"),
        "source_title": seed.get("source_title"),
        "url": row.get("input_url"),
        "final_url": row.get("final_url") or row.get("canonical_url"),
        "platform": row.get("platform"),
        "profile_display_name": row.get("profile_display_name"),
        "profile_handle": row.get("profile_handle"),
        "rendered_title": row.get("rendered_title"),
        "bio_excerpt": row.get("bio_excerpt"),
        "external_links": row.get("external_links") if isinstance(row.get("external_links"), list) else [],
        "identity_proof": False,
        "accepted_for_graph": False,
        "graph_write_allowed": False,
        "review_required": True,
        "review_reason": "OpenCLI profile metadata is direct profile-content context, but identity acceptance requires manual source-backed review.",
        "next_action": "manual_profile_text_vs_source_article_review",
        "unsafe_action": bool(row.get("unsafe_action")),
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


def build_review_queue(
    *,
    seed_queue: Path,
    http_results: Path,
    opencli_evidence: Path,
    maigret_evidence: Path,
    out_dir: Path,
) -> dict[str, Any]:
    reject_broad_d_path(out_dir, "out_dir")
    seed_rows = read_jsonl(seed_queue)
    _seed_by_id, seed_by_url = seed_indexes(seed_rows)
    http_rows = read_jsonl(http_results)
    opencli_rows = read_jsonl(opencli_evidence)
    maigret_rows = read_jsonl(maigret_evidence)

    normalized_http = [item for row in http_rows if (item := normalize_http_row(row))]
    normalized_opencli = [item for row in opencli_rows if (item := normalize_opencli_row(row, seed_by_url))]
    normalized_maigret = [normalize_maigret_row(row) for row in maigret_rows]
    combined = normalized_http + normalized_opencli + normalized_maigret

    out_dir.mkdir(parents=True, exist_ok=True)
    http_path = out_dir / "http_fast_identity_review_queue.jsonl"
    opencli_path = out_dir / "opencli_identity_review_queue.jsonl"
    maigret_path = out_dir / "maigret_identity_review_queue.jsonl"
    combined_path = out_dir / "external_identity_review_queue.jsonl"
    write_jsonl(http_path, normalized_http)
    write_jsonl(opencli_path, normalized_opencli)
    write_jsonl(maigret_path, normalized_maigret)
    write_jsonl(combined_path, combined)

    family_counts = Counter(row["source_family"] for row in combined)
    tier_counts = Counter(row["review_tier"] for row in combined)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "atlas_open_source_phase1_review_queue_ready",
        "seed_queue": str(seed_queue),
        "http_results": str(http_results),
        "opencli_evidence": str(opencli_evidence),
        "maigret_evidence": str(maigret_evidence),
        "http_review_path": str(http_path),
        "opencli_review_path": str(opencli_path),
        "maigret_review_path": str(maigret_path),
        "combined_review_path": str(combined_path),
        "seed_rows_seen": len(seed_rows),
        "http_rows_seen": len(http_rows),
        "http_review_rows": len(normalized_http),
        "opencli_rows_seen": len(opencli_rows),
        "opencli_review_rows": len(normalized_opencli),
        "maigret_rows_seen": len(maigret_rows),
        "maigret_review_rows": len(normalized_maigret),
        "combined_review_rows": len(combined),
        "family_counts": dict(sorted(family_counts.items())),
        "tier_counts": dict(sorted(tier_counts.items())),
        "accepted_for_graph": 0,
        "safety": {
            "report_only": True,
            "accepted_for_graph": 0,
            "cookie_or_token_exported": False,
            "d_scan_executed": False,
            "graph_write_executed": False,
            "model_call_executed": False,
            "paid_api_used": False,
            "qdrant_write_executed": False,
            "sqlite_write_executed": False,
        },
        "next_gate": "Run strict adjudication, then manual review; keep accepted edges empty until explicit acceptance.",
    }
    write_json(out_dir / "external_identity_review_queue_summary.json", summary)
    write_markdown(out_dir / "external_identity_review_queue_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Atlas Open Source Stack Phase 1 Review Queue",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- combined_review_rows: `{summary['combined_review_rows']}`",
        f"- http_review_rows: `{summary['http_review_rows']}`",
        f"- opencli_review_rows: `{summary['opencli_review_rows']}`",
        f"- maigret_review_rows: `{summary['maigret_review_rows']}`",
        f"- accepted_for_graph: `{summary['accepted_for_graph']}`",
        f"- family_counts: `{json.dumps(summary['family_counts'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Outputs",
        "",
        f"- combined_review_path: `{summary['combined_review_path']}`",
        f"- http_review_path: `{summary['http_review_path']}`",
        f"- opencli_review_path: `{summary['opencli_review_path']}`",
        f"- maigret_review_path: `{summary['maigret_review_path']}`",
        "",
        "## Safety",
        "",
        "- Report-only review queue builder.",
        "- No graph/vector/SQLite write, model call, paid API, cookie/token export, or D: scan.",
        "- OpenCLI metadata is review context only; accepted graph edge output remains empty until manual acceptance.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-queue", type=Path, default=DEFAULT_SEED_QUEUE)
    parser.add_argument("--http-results", type=Path, default=DEFAULT_HTTP_RESULTS)
    parser.add_argument("--opencli-evidence", type=Path, default=DEFAULT_OPENCLI_EVIDENCE)
    parser.add_argument("--maigret-evidence", type=Path, default=DEFAULT_MAIGRET_EVIDENCE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_review_queue(
        seed_queue=args.seed_queue,
        http_results=args.http_results,
        opencli_evidence=args.opencli_evidence,
        maigret_evidence=args.maigret_evidence,
        out_dir=args.out_dir,
    )
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "combined_review_rows": summary["combined_review_rows"],
                "summary": str(args.out_dir / "external_identity_review_queue_summary.json"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
