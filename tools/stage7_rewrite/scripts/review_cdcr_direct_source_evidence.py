#!/usr/bin/env python3
"""Build a PRD-02 CDCR direct-source quality review pack.

This report-only gate reviews existing CDCR public-source validation rows and
optionally cross-references existing OpenCLI identity review rows. It does not
fetch URLs, accept graph edges, or write Neo4j/vector/DB state.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_CDCR_EVIDENCE = Path("reports/p1_cdcr_direct_source_20260515/cdcr_direct_evidence.jsonl")
DEFAULT_OPENCLI_REVIEW = Path("reports/opencli_social_identity_review_20260516/opencli_identity_review.jsonl")
DEFAULT_OUT_DIR = Path("reports/p1_cdcr_direct_source_review_20260516")
SCHEMA_VERSION = "stage7_p1_cdcr_direct_source_review.v1"
PROFILE_SOURCE_TYPES = {"artist_profile", "bandcamp_artist", "music_profile"}
SUPPORTING_SOURCE_TYPES = {"radio_show", "soundcloud_track", "event_lineup", "bilibili_search"}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for CDCR source review: {path}")


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


def subject_key(value: str) -> str:
    return first_text(value).casefold()


def group_by_subject(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[subject_key(first_text(row.get("subject_name")))].append(row)
    return grouped


def opencli_by_subject(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[subject_key(first_text(row.get("subject_name")))].append(row)
    return grouped


def build_subject_review(subject: str, cdcr_rows: list[dict[str, Any]], opencli_rows: list[dict[str, Any]]) -> dict[str, Any]:
    direct_rows = [row for row in cdcr_rows if bool(row.get("direct_source_candidate"))]
    reachable_rows = [row for row in cdcr_rows if bool(row.get("accessible"))]
    profile_rows = [row for row in direct_rows if first_text(row.get("source_type")) in PROFILE_SOURCE_TYPES]
    supporting_rows = [row for row in direct_rows if first_text(row.get("source_type")) in SUPPORTING_SOURCE_TYPES]
    strong_opencli_rows = [
        row for row in opencli_rows if first_text(row.get("review_tier")) == "strong_opencli_review_candidate"
    ]
    if profile_rows and strong_opencli_rows:
        review_status = "source_backed_profile_review_candidate"
    elif profile_rows:
        review_status = "profile_source_review_candidate"
    elif direct_rows:
        review_status = "supporting_direct_source_review_candidate"
    else:
        review_status = "no_direct_source_found"
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "subject_name": subject,
        "candidate_rows": len(cdcr_rows),
        "reachable_rows": len(reachable_rows),
        "direct_source_candidates": len(direct_rows),
        "profile_source_candidates": len(profile_rows),
        "supporting_source_candidates": len(supporting_rows),
        "opencli_review_rows": len(opencli_rows),
        "strong_opencli_review_rows": len(strong_opencli_rows),
        "source_types": dict(Counter(first_text(row.get("source_type")) or "unknown" for row in cdcr_rows)),
        "best_candidate_urls": [first_text(row.get("source_url")) for row in profile_rows[:3] or direct_rows[:3]],
        "review_status": review_status,
        "identity_proof": False,
        "accepted_for_graph": False,
        "graph_ready": False,
        "review_required": True,
        "review_reason": "CDCR source candidates need source-backed identity acceptance before graph use.",
    }


def build_review(cdcr_evidence: Path, opencli_review: Path, out_dir: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    cdcr_rows = read_jsonl(cdcr_evidence)
    opencli_rows = read_jsonl(opencli_review)
    grouped_cdcr = group_by_subject(cdcr_rows)
    grouped_opencli = opencli_by_subject(opencli_rows)
    subject_names = sorted(
        {first_text(row.get("subject_name")) for row in cdcr_rows if first_text(row.get("subject_name"))},
        key=lambda value: value.casefold(),
    )
    review_rows = [
        build_subject_review(subject, grouped_cdcr[subject_key(subject)], grouped_opencli.get(subject_key(subject), []))
        for subject in subject_names
    ]
    status_counts = Counter(first_text(row.get("review_status")) or "unknown" for row in review_rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    review_path = out_dir / "cdcr_direct_source_review.jsonl"
    summary_path = out_dir / "cdcr_direct_source_review_summary.json"
    accepted_path = out_dir / "accepted_cdcr_graph_edges.jsonl"
    write_jsonl(review_path, review_rows)
    write_jsonl(accepted_path, [])
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "cdcr_direct_source_review_ready" if review_rows else "cdcr_direct_source_review_empty",
        "cdcr_evidence_path": str(cdcr_evidence),
        "opencli_review_path": str(opencli_review),
        "review_path": str(review_path),
        "accepted_edges_path": str(accepted_path),
        "subject_count": len(review_rows),
        "candidate_rows": len(cdcr_rows),
        "reachable_rows": sum(1 for row in cdcr_rows if bool(row.get("accessible"))),
        "direct_source_candidates": sum(1 for row in cdcr_rows if bool(row.get("direct_source_candidate"))),
        "source_backed_profile_review_candidates": int(status_counts.get("source_backed_profile_review_candidate") or 0),
        "profile_source_review_candidates": int(status_counts.get("profile_source_review_candidate") or 0),
        "supporting_direct_source_review_candidates": int(
            status_counts.get("supporting_direct_source_review_candidate") or 0
        ),
        "no_direct_source_found_subjects": int(status_counts.get("no_direct_source_found") or 0),
        "status_counts": dict(status_counts),
        "accepted_edges": 0,
        "graph_ready_rows": 0,
        "identity_proof_rows": 0,
        "blockers": [
            "CDCR evidence is review-ready but not identity proof",
            "accepted_edges remains 0 until source-backed acceptance criteria are explicitly met",
            "Neo4j graph promotion remains blocked",
        ],
        "allowed_next_actions": [
            "use source_backed_profile_review_candidate subjects for manual/source-backed acceptance review",
            "keep accepted edge file empty until acceptance criteria are met",
        ],
        "forbidden_next_actions": [
            "do_not_treat_bilibili_search_or_event_lineup_as_identity_proof",
            "do_not_auto_accept_cdcr_edges",
            "do_not_write_neo4j_from_cdcr_review_candidates",
        ],
        "safety": [
            "reports_only",
            "existing_cdcr_evidence_only",
            "existing_opencli_review_only",
            "accepted_edges_empty",
            "no_network_calls",
            "no_login",
            "no_cookies",
            "no_graph_vector_db_write",
            "no_paid_api",
            "no_d_scan",
            "no_publish",
        ],
        "writes": "reports_only",
    }
    write_json(summary_path, summary)
    write_markdown(out_dir / "cdcr_direct_source_review_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# PRD-02 CDCR Direct Source Review",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- subject_count: `{summary['subject_count']}`",
        f"- candidate_rows: `{summary['candidate_rows']}`",
        f"- direct_source_candidates: `{summary['direct_source_candidates']}`",
        f"- source_backed_profile_review_candidates: `{summary['source_backed_profile_review_candidates']}`",
        f"- profile_source_review_candidates: `{summary['profile_source_review_candidates']}`",
        f"- supporting_direct_source_review_candidates: `{summary['supporting_direct_source_review_candidates']}`",
        f"- accepted_edges: `{summary['accepted_edges']}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in sorted(summary["status_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Safety", ""])
    for item in summary["safety"]:
        lines.append(f"- {item}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdcr-evidence", type=Path, default=DEFAULT_CDCR_EVIDENCE)
    parser.add_argument("--opencli-review", type=Path, default=DEFAULT_OPENCLI_REVIEW)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    summary = build_review(args.cdcr_evidence, args.opencli_review, args.out_dir)
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "subject_count": summary["subject_count"],
                "source_backed_profile_review_candidates": summary["source_backed_profile_review_candidates"],
                "accepted_edges": summary["accepted_edges"],
                "summary": str(args.out_dir / "cdcr_direct_source_review_summary.json"),
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
