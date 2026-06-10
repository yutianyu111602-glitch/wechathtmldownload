#!/usr/bin/env python3
"""Build a report-only decision packet for recovered source-context candidates.

This P3-S3 runner consumes the P3-S2 local source-context recovery output. It
does not fetch profile pages and never accepts graph edges. The output only
separates rows into future direct-proof-pass, review-only, and rejected-for-now
queues for the next bounded production step.
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
from urllib.parse import urlparse


DEFAULT_INPUT = Path(
    "reports/external_identity_source_context_recovery_47k_delta375_20260519/source_context_recovered_candidates.jsonl"
)
DEFAULT_OUT_DIR = Path("reports/external_identity_source_context_decision_47k_delta375_20260519")
SCHEMA_VERSION = "stage7_graph_external_identity_source_context_decision.v1"

FUTURE_PROOF_TYPES = {"person", "organization", "collective", "venue", "label"}
CONTEXT_ONLY_TYPES = {"event", "brand", "place", "work"}
GENERIC_CANDIDATE_NAMES = {"bandcamp", "bilibili", "swinedaily"}
DIRECT_PROOF_DOMAINS = {
    "baihui.live",
    "beatport.com",
    "facebook.com",
    "instagram.com",
    "mixcloud.com",
    "site.douban.com",
    "soundcloud.com",
    "t.me",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for source-context decision: {path}")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def normalize(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.casefold())


def url_domain(url: str) -> str:
    host = (urlparse(url).hostname or "").casefold()
    if host.startswith("www."):
        host = host[4:]
    return host


def is_track_or_article_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.casefold()
    host = (parsed.hostname or "").casefold()
    if "mp.weixin.qq.com" in host:
        return True
    if "bilibili.com" in host and ("/video/" in path or "/live/" in path):
        return True
    if "bandcamp.com" in host and ("/track/" in path or "/album/" in path):
        return True
    if "swinedaily.com" in host and len(path.strip("/").split("/")) >= 1:
        return True
    return False


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "input")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
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


def candidate_types(row: dict[str, Any]) -> set[str]:
    types: set[str] = set()
    for entity in row.get("candidate_entities") or []:
        if isinstance(entity, dict):
            value = first_text(entity.get("type")).casefold()
            if value:
                types.add(value)
    return types


def candidate_names(row: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for entity in row.get("candidate_entities") or []:
        if isinstance(entity, dict):
            value = normalize(first_text(entity.get("name")))
            if value:
                names.add(value)
    return names


def decide_row(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    url = first_text(row.get("url"))
    domain = url_domain(url)
    types = candidate_types(row)
    names = candidate_names(row)
    handle = first_text(row.get("handle_hint"))
    subject = first_text(row.get("subject_name"))
    has_future_type = bool(types & FUTURE_PROOF_TYPES)
    only_context_type = bool(types) and types <= CONTEXT_ONLY_TYPES
    has_generic_only_candidate = bool(names) and names <= {normalize(name) for name in GENERIC_CANDIDATE_NAMES}
    profile_domain = any(domain == item or domain.endswith("." + item) for item in DIRECT_PROOF_DOMAINS)
    title_context = bool(row.get("source_title_match") or row.get("article_title_match"))
    row_context = first_text(row.get("recovery_status"))
    reasons: list[str] = [
        "source_context_only_not_identity_proof",
        "no_external_profile_page_fetched_in_this_step",
    ]

    if only_context_type:
        bucket = "rejected_for_graph_now"
        reasons.append("candidate_entity_type_is_event_brand_place_or_work_only")
    elif has_generic_only_candidate:
        bucket = "rejected_for_graph_now"
        reasons.append("candidate_name_is_generic_platform_or_publisher")
    elif is_track_or_article_url(url):
        bucket = "review_only"
        reasons.append("url_points_to_track_album_video_live_or_article_not_profile")
    elif has_future_type and profile_domain and len(normalize(handle)) >= 4:
        bucket = "future_direct_proof_pass"
        reasons.append("person_or_organization_context_plus_public_profile_domain")
        if subject:
            reasons.append("subject_name_present")
        if title_context:
            reasons.append("title_or_article_context_matches")
        if row_context == "subject_candidates_recovered_from_local_article":
            reasons.append("subject_candidates_recovered_from_local_article")
    else:
        bucket = "review_only"
        reasons.append("ambiguous_context_requires_manual_review_before_future_fetch")

    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "decided_at": generated_at,
        "row_index": row.get("row_index"),
        "source_article_uid": first_text(row.get("source_article_uid")),
        "source_title": first_text(row.get("source_title")),
        "subject_name": subject,
        "url": url,
        "domain": domain,
        "handle_hint": handle,
        "candidate_types": sorted(types),
        "recovered_subject_candidates": row.get("recovered_subject_candidates") or [],
        "decision_bucket": bucket,
        "decision_reasons": reasons,
        "accepted_for_graph": False,
        "identity_proof": False,
        "graph_write_allowed": False,
    }


def build_packet(*, input_path: Path, out_dir: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    rows = read_jsonl(input_path)
    generated_at = now_iso()
    decisions = [decide_row(row, generated_at) for row in rows]
    buckets = Counter(row["decision_bucket"] for row in decisions)

    future_rows = [row for row in decisions if row["decision_bucket"] == "future_direct_proof_pass"]
    review_rows = [row for row in decisions if row["decision_bucket"] == "review_only"]
    rejected_rows = [row for row in decisions if row["decision_bucket"] == "rejected_for_graph_now"]
    accepted_rows: list[dict[str, Any]] = []

    out_dir.mkdir(parents=True, exist_ok=True)
    decision_path = out_dir / "source_context_decision.jsonl"
    future_path = out_dir / "future_direct_proof_pass_queue.jsonl"
    review_path = out_dir / "review_only_context_queue.jsonl"
    rejected_path = out_dir / "rejected_source_context_only_for_graph.jsonl"
    accepted_path = out_dir / "accepted_external_identity_edges_for_graph.jsonl"

    write_jsonl(decision_path, decisions)
    write_jsonl(future_path, future_rows)
    write_jsonl(review_path, review_rows)
    write_jsonl(rejected_path, rejected_rows)
    write_jsonl(accepted_path, accepted_rows)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "ok": True,
        "decision": "external_identity_source_context_decision_ready_no_graph_acceptance",
        "input_path": str(input_path),
        "decision_path": str(decision_path),
        "future_direct_proof_pass_queue_path": str(future_path),
        "review_only_context_queue_path": str(review_path),
        "rejected_source_context_only_for_graph_path": str(rejected_path),
        "accepted_edges_path": str(accepted_path),
        "input_rows": len(rows),
        "decision_counts": dict(sorted(buckets.items())),
        "future_direct_proof_pass_rows": len(future_rows),
        "review_only_rows": len(review_rows),
        "rejected_for_graph_now_rows": len(rejected_rows),
        "accepted_for_graph": 0,
        "safety": {
            "report_only": True,
            "network_call_executed": False,
            "profile_page_fetch_executed": False,
            "graph_write_executed": False,
            "qdrant_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
        },
    }
    write_json(out_dir / "source_context_decision_summary.json", summary)
    write_markdown(out_dir / "source_context_decision_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# External Identity Source Context Decision Packet",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- input_rows: `{summary['input_rows']}`",
        f"- future_direct_proof_pass_rows: `{summary['future_direct_proof_pass_rows']}`",
        f"- review_only_rows: `{summary['review_only_rows']}`",
        f"- rejected_for_graph_now_rows: `{summary['rejected_for_graph_now_rows']}`",
        f"- accepted_for_graph: `{summary['accepted_for_graph']}`",
        f"- decision_path: `{summary['decision_path']}`",
        f"- future_direct_proof_pass_queue_path: `{summary['future_direct_proof_pass_queue_path']}`",
        f"- review_only_context_queue_path: `{summary['review_only_context_queue_path']}`",
        f"- rejected_source_context_only_for_graph_path: `{summary['rejected_source_context_only_for_graph_path']}`",
        f"- accepted_edges_path: `{summary['accepted_edges_path']}`",
        "",
        "## Decision Counts",
        "",
    ]
    for key, value in sorted(summary["decision_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only source-context decision packet.",
            "- No external profile pages fetched.",
            "- No graph/vector/DB/mem0 writes.",
            "- Accepted graph edge output remains empty.",
            "",
            "## Next Gate",
            "",
            "Rows in `future_direct_proof_pass_queue.jsonl` still require direct profile/source content proof before any graph edge can be accepted.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    summary = build_packet(input_path=args.input, out_dir=args.out_dir)
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "input_rows": summary["input_rows"],
                "decision_counts": summary["decision_counts"],
                "accepted_for_graph": summary["accepted_for_graph"],
                "summary": str(args.out_dir / "source_context_decision_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
