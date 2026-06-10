#!/usr/bin/env python3
"""Build PRD-16 social identity cross-evidence review pack.

This is a report-only review aid. It scores existing public social edge
candidates against deterministic cross-evidence signals, but it does not accept
edges or write Neo4j. Public reachability and string matches are review signals,
not identity proof.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_CANDIDATES = Path("reports/social_deep_edge_pack_20260515/social_deep_edge_candidates.jsonl")
DEFAULT_OUT_DIR = Path("reports/social_identity_cross_evidence_20260515")
SCHEMA_VERSION = "stage7_social_identity_cross_evidence_review.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for PRD-16 identity review: {path}")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
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


def normalize_compact(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.casefold())


def normalize_words(value: str) -> list[str]:
    return [part for part in re.split(r"[^0-9a-z\u4e00-\u9fff]+", value.casefold()) if part]


def contains_all_subject_words(subject: str, haystack: str) -> bool:
    words = normalize_words(subject)
    if not words:
        return False
    compact_haystack = normalize_compact(haystack)
    return all(word and word in compact_haystack for word in words)


def score_candidate(row: dict[str, Any]) -> dict[str, Any]:
    subject = first_text(row.get("subject_name"))
    title = first_text(row.get("object_title"))
    object_url = first_text(row.get("object_url"))
    evidence_url = first_text(row.get("evidence_url"))
    title_match = contains_all_subject_words(subject, title)
    object_url_match = contains_all_subject_words(subject, object_url)
    evidence_url_match = contains_all_subject_words(subject, evidence_url)
    title_structure = bool(re.search(r"\b(stream|music)\b|\|", title.casefold()))
    platform_reachable = first_text(row.get("verification_status")) == "public_profile_reachable"
    signals = {
        "subject_in_object_title": title_match,
        "subject_in_object_url": object_url_match,
        "subject_in_source_evidence_url": evidence_url_match,
        "profile_title_has_music_context": title_structure,
        "public_profile_reachable": platform_reachable,
    }
    score = sum(1 for value in signals.values() if value)
    if title_match and object_url_match and evidence_url_match:
        tier = "strong_review_candidate"
    elif score >= 3 and title_match:
        tier = "medium_review_candidate"
    else:
        tier = "weak_or_reachability_only"
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "edge_id": row.get("edge_id"),
        "subject_name": subject,
        "object_platform": row.get("object_platform"),
        "object_url": object_url,
        "object_title": title,
        "evidence_url": evidence_url,
        "source_family": row.get("source_family"),
        "edge_type": row.get("edge_type"),
        "signals": signals,
        "identity_signal_score": score,
        "review_tier": tier,
        "identity_proof": False,
        "accepted_for_staging": False,
        "graph_ready": False,
        "review_required": True,
        "review_reason": "Deterministic cross-evidence signals are review aids, not identity proof.",
        "staging_only": True,
    }


def build_review(candidates_path: Path, out_dir: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    source_rows = read_jsonl(candidates_path)
    review_rows = [score_candidate(row) for row in source_rows]
    tier_counts = Counter(row["review_tier"] for row in review_rows)
    platform_counts = Counter(first_text(row.get("object_platform")) or "unknown" for row in review_rows)
    accepted_rows: list[dict[str, Any]] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    review_path = out_dir / "identity_cross_evidence_review.jsonl"
    accepted_path = out_dir / "accepted_social_edges_after_identity_review.jsonl"
    write_jsonl(review_path, review_rows)
    write_jsonl(accepted_path, accepted_rows)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "social_identity_cross_evidence_review_ready" if review_rows else "social_identity_cross_evidence_empty",
        "candidates_path": str(candidates_path),
        "review_path": str(review_path),
        "accepted_edges_path": str(accepted_path),
        "candidate_edges_seen": len(source_rows),
        "review_rows": len(review_rows),
        "accepted_edges": 0,
        "tier_counts": dict(tier_counts),
        "platform_counts": dict(platform_counts),
        "strong_review_candidates": int(tier_counts.get("strong_review_candidate") or 0),
        "medium_review_candidates": int(tier_counts.get("medium_review_candidate") or 0),
        "weak_or_reachability_only": int(tier_counts.get("weak_or_reachability_only") or 0),
        "blockers": [
            "identity cross-evidence is deterministic string evidence only",
            "accepted_edges remains 0 until human or stricter source-backed review is added",
            "Neo4j staging write remains blocked for PRD-16 social deep candidates",
        ],
        "allowed_next_actions": [
            "review strong_review_candidate rows manually or with a stricter source-backed identity contract",
            "keep accepted edge file empty until review accepts specific rows",
        ],
        "forbidden_next_actions": [
            "do_not_treat_public_reachability_as_identity_proof",
            "do_not_auto_accept_edges_from_string_matches",
            "do_not_run_instagram_login_crawling",
            "do_not_write_neo4j_from_review_candidates",
        ],
        "safety": [
            "reports_only",
            "existing_candidate_edges_only",
            "accepted_edges_empty",
            "no_login",
            "no_cookies",
            "no_network_calls",
            "no_graph_vector_db_write",
            "no_paid_api",
            "no_d_scan",
            "no_publish",
        ],
        "writes": "reports_only",
    }
    write_json(out_dir / "identity_cross_evidence_summary.json", summary)
    write_markdown(out_dir / "identity_cross_evidence_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# PRD-16 Identity Cross-Evidence Review",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- candidate_edges_seen: `{summary['candidate_edges_seen']}`",
        f"- review_rows: `{summary['review_rows']}`",
        f"- accepted_edges: `{summary['accepted_edges']}`",
        f"- strong_review_candidates: `{summary['strong_review_candidates']}`",
        f"- medium_review_candidates: `{summary['medium_review_candidates']}`",
        f"- weak_or_reachability_only: `{summary['weak_or_reachability_only']}`",
        f"- review_path: `{summary['review_path']}`",
        f"- accepted_edges_path: `{summary['accepted_edges_path']}`",
        "",
        "## Tier Counts",
        "",
    ]
    for key, value in sorted(summary["tier_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Platform Counts", ""])
    for key, value in sorted(summary["platform_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Blockers", ""])
    for blocker in summary["blockers"]:
        lines.append(f"- {blocker}")
    lines.extend(["", "## Safety", ""])
    for item in summary["safety"]:
        lines.append(f"- {item}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    summary = build_review(args.candidates, args.out_dir)
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "candidate_edges_seen": summary["candidate_edges_seen"],
                "accepted_edges": summary["accepted_edges"],
                "strong_review_candidates": summary["strong_review_candidates"],
                "report": str(args.out_dir / "identity_cross_evidence_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if summary["ok"] or args.report_only_exit_zero else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
