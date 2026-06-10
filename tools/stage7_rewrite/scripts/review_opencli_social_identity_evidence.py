#!/usr/bin/env python3
"""Review PRD-16 OpenCLI social evidence against identity candidates.

This report-only gate joins existing OpenCLI browser evidence with the existing
identity cross-evidence review rows. It ranks candidates for stricter review,
but it never accepts edges automatically and never writes graph/vector/DB state.
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


DEFAULT_OPENCLI_EVIDENCE = Path("reports/opencli_social_profile_evidence_20260516/social_profile_evidence.jsonl")
DEFAULT_IDENTITY_REVIEW = Path("reports/social_identity_cross_evidence_20260515/identity_cross_evidence_review.jsonl")
DEFAULT_OUT_DIR = Path("reports/opencli_social_identity_review_20260516")
SCHEMA_VERSION = "stage7_prd16_opencli_social_identity_review.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for PRD-16 OpenCLI identity review: {path}")


def first_text(value: Any) -> str:
    return str(value or "").strip()


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


def normalize_compact(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.casefold())


def normalize_words(value: str) -> list[str]:
    return [part for part in re.split(r"[^0-9a-z\u4e00-\u9fff]+", value.casefold()) if part]


def contains_all_subject_words(subject: str, haystack: str) -> bool:
    words = normalize_words(subject)
    if not words:
        return False
    compact = normalize_compact(haystack)
    return all(word in compact for word in words)


def external_links(row: dict[str, Any]) -> list[dict[str, Any]]:
    value = row.get("external_links")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def row_haystack(row: dict[str, Any]) -> str:
    links = external_links(row)
    link_text = " ".join(
        first_text(item.get("text")) + " " + first_text(item.get("url")) + " " + first_text(item.get("domain"))
        for item in links
    )
    return " ".join(
        [
            first_text(row.get("profile_display_name")),
            first_text(row.get("profile_handle")),
            first_text(row.get("rendered_title")),
            first_text(row.get("bio_excerpt")),
            first_text(row.get("canonical_url")),
            first_text(row.get("final_url")),
            link_text,
        ]
    )


def score_opencli_row(row: dict[str, Any], identity_by_edge_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source_row_id = first_text(row.get("source_row_id"))
    identity = identity_by_edge_id.get(source_row_id, {})
    subject = first_text(row.get("subject_name") or identity.get("subject_name"))
    links = external_links(row)
    signals = {
        "opencli_report_ready": first_text(row.get("decision")) == "report_ready",
        "unsafe_action_false": row.get("unsafe_action") is False,
        "no_opencli_error": not first_text(row.get("opencli_error")),
        "subject_in_rendered_profile": contains_all_subject_words(subject, row_haystack(row)),
        "profile_image_hash_present": first_text(row.get("profile_image_url_or_hash")).startswith("sha256:"),
        "external_links_present": bool(links),
        "source_status_strong": first_text(row.get("source_status")) == "strong_review_candidate",
        "identity_review_strong": first_text(identity.get("review_tier")) == "strong_review_candidate",
    }
    score = sum(1 for value in signals.values() if value)
    if row.get("unsafe_action") is not False:
        tier = "unsafe_reject"
    elif (
        signals["opencli_report_ready"]
        and signals["unsafe_action_false"]
        and signals["subject_in_rendered_profile"]
        and (signals["source_status_strong"] or signals["identity_review_strong"])
        and (signals["external_links_present"] or signals["profile_image_hash_present"])
    ):
        tier = "strong_opencli_review_candidate"
    elif signals["opencli_report_ready"] and signals["subject_in_rendered_profile"]:
        tier = "medium_opencli_review_candidate"
    else:
        tier = "needs_identity_review"
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "source_row_id": source_row_id,
        "subject_name": subject,
        "platform": row.get("platform"),
        "canonical_url": row.get("canonical_url"),
        "profile_display_name": row.get("profile_display_name"),
        "profile_handle": row.get("profile_handle"),
        "source_status": row.get("source_status"),
        "identity_review_tier": identity.get("review_tier"),
        "signals": signals,
        "opencli_identity_signal_score": score,
        "review_tier": tier,
        "external_link_domains": sorted(
            {first_text(item.get("domain")) for item in links if first_text(item.get("domain"))}
        ),
        "identity_proof": False,
        "accepted_for_staging": False,
        "graph_ready": False,
        "review_required": True,
        "review_reason": "OpenCLI rendered evidence strengthens review context but is not automatic identity proof.",
        "staging_only": True,
    }


def build_review(opencli_evidence: Path, identity_review: Path, out_dir: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    evidence_rows = read_jsonl(opencli_evidence)
    identity_rows = read_jsonl(identity_review)
    identity_by_edge_id = {first_text(row.get("edge_id")): row for row in identity_rows if first_text(row.get("edge_id"))}
    review_rows = [score_opencli_row(row, identity_by_edge_id) for row in evidence_rows]
    tier_counts = Counter(first_text(row.get("review_tier")) or "unknown" for row in review_rows)
    platform_counts = Counter(first_text(row.get("platform")) or "unknown" for row in review_rows)
    matched_identity_rows = sum(1 for row in evidence_rows if first_text(row.get("source_row_id")) in identity_by_edge_id)
    accepted_rows: list[dict[str, Any]] = []

    out_dir.mkdir(parents=True, exist_ok=True)
    review_path = out_dir / "opencli_identity_review.jsonl"
    accepted_path = out_dir / "accepted_social_edges_after_opencli_review.jsonl"
    summary_path = out_dir / "opencli_identity_review_summary.json"
    write_jsonl(review_path, review_rows)
    write_jsonl(accepted_path, accepted_rows)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "opencli_identity_review_ready" if review_rows else "opencli_identity_review_empty",
        "opencli_evidence_path": str(opencli_evidence),
        "identity_review_path": str(identity_review),
        "review_path": str(review_path),
        "accepted_edges_path": str(accepted_path),
        "opencli_evidence_rows": len(evidence_rows),
        "identity_review_rows": len(identity_rows),
        "matched_identity_rows": matched_identity_rows,
        "review_rows": len(review_rows),
        "accepted_edges": 0,
        "strong_opencli_review_candidates": int(tier_counts.get("strong_opencli_review_candidate") or 0),
        "medium_opencli_review_candidates": int(tier_counts.get("medium_opencli_review_candidate") or 0),
        "unsafe_reject_rows": int(tier_counts.get("unsafe_reject") or 0),
        "tier_counts": dict(tier_counts),
        "platform_counts": dict(platform_counts),
        "rows_with_external_links": sum(1 for row in evidence_rows if external_links(row)),
        "blockers": [
            "OpenCLI evidence is review context, not automatic identity proof",
            "accepted_edges remains 0 until a separate source-backed acceptance gate exists",
            "Neo4j staging write remains blocked for PRD-16 social deep candidates",
        ],
        "allowed_next_actions": [
            "use strong_opencli_review_candidate rows for manual/source-backed acceptance review",
            "keep accepted edge file empty until acceptance criteria are explicitly met",
        ],
        "forbidden_next_actions": [
            "do_not_export_cookie_or_token",
            "do_not_perform_social_account_actions",
            "do_not_collect_private_or_follower_only_content",
            "do_not_auto_accept_edges_from_logged_in_visibility",
            "do_not_write_neo4j_from_opencli_review_candidates",
        ],
        "safety": [
            "reports_only",
            "existing_opencli_evidence_only",
            "accepted_edges_empty",
            "no_cookie_token_export",
            "no_account_action",
            "no_private_collection",
            "no_network_calls",
            "no_graph_vector_db_write",
            "no_paid_api",
            "no_d_scan",
            "no_publish",
        ],
        "writes": "reports_only",
    }
    write_json(summary_path, summary)
    write_markdown(out_dir / "opencli_identity_review_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# PRD-16 OpenCLI Social Identity Review",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- opencli_evidence_rows: `{summary['opencli_evidence_rows']}`",
        f"- matched_identity_rows: `{summary['matched_identity_rows']}`",
        f"- review_rows: `{summary['review_rows']}`",
        f"- accepted_edges: `{summary['accepted_edges']}`",
        f"- strong_opencli_review_candidates: `{summary['strong_opencli_review_candidates']}`",
        f"- medium_opencli_review_candidates: `{summary['medium_opencli_review_candidates']}`",
        f"- rows_with_external_links: `{summary['rows_with_external_links']}`",
        "",
        "## Tier Counts",
        "",
    ]
    for key, value in sorted(summary["tier_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Platform Counts", ""])
    for key, value in sorted(summary["platform_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Safety", ""])
    for item in summary["safety"]:
        lines.append(f"- {item}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opencli-evidence", type=Path, default=DEFAULT_OPENCLI_EVIDENCE)
    parser.add_argument("--identity-review", type=Path, default=DEFAULT_IDENTITY_REVIEW)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    summary = build_review(args.opencli_evidence, args.identity_review, args.out_dir)
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "opencli_evidence_rows": summary["opencli_evidence_rows"],
                "strong_opencli_review_candidates": summary["strong_opencli_review_candidates"],
                "accepted_edges": summary["accepted_edges"],
                "summary": str(args.out_dir / "opencli_identity_review_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if summary["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
