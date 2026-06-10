#!/usr/bin/env python3
"""Build a strict review gate over external identity source follow-up rows.

This P2-S3 report-only gate compresses bounded public source/profile follow-up
results into rejected/needs-more-source/accepted outputs. It intentionally keeps
accepted graph edges empty unless a stricter downstream gate is added.
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


DEFAULT_FOLLOWUP_REVIEWS = [
    Path("reports/external_identity_source_followup_47k_delta375_20260519/source_followup_review.jsonl"),
    Path("reports/external_identity_source_followup_candidate_only_47k_delta375_20260519/source_followup_review.jsonl"),
]
DEFAULT_OUT_DIR = Path("reports/external_identity_source_followup_review_gate_47k_delta375_20260519")
SCHEMA_VERSION = "stage7_graph_external_identity_source_followup_review_gate.v1"

GENERIC_PROFILE_MARKERS = {
    "github",
    "gists",
    "reddit",
    "flickr",
    "instagram photos and videos",
    "picnob",
    "tiktok",
    "tikbuddy",
    "vk.com",
    "wikipedia",
    "coder social",
    "page not found",
    "just a moment",
    "please wait for verification",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for follow-up review gate: {path}")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_compact(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.casefold())


def token_present(haystack: str, needle: str) -> bool:
    normalized = normalize_compact(needle)
    if len(normalized) < 3:
        return False
    return normalized in normalize_compact(haystack)


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


def profile_text(row: dict[str, Any]) -> str:
    fields = [
        row.get("profile_title"),
        row.get("profile_og_title"),
        row.get("profile_description"),
        row.get("profile_og_description"),
        row.get("profile_visible_excerpt"),
        row.get("profile_canonical_url"),
        row.get("final_url"),
    ]
    return " | ".join(first_text(value) for value in fields if first_text(value))


def generic_profile_like(row: dict[str, Any]) -> bool:
    text = profile_text(row).casefold()
    return any(marker in text for marker in GENERIC_PROFILE_MARKERS)


def review_row(row: dict[str, Any]) -> dict[str, Any]:
    subject = first_text(row.get("subject_name"))
    source_title = first_text(row.get("source_title"))
    text = profile_text(row)
    signals = row.get("signals") if isinstance(row.get("signals"), dict) else {}
    subject_in_profile = bool(signals.get("subject_in_profile_text")) or (bool(subject) and token_present(text, subject))
    subject_in_source = bool(signals.get("subject_in_source_title")) or (bool(subject) and token_present(source_title, subject))
    handle_in_profile = bool(signals.get("handle_in_profile_text"))
    handle_in_source = bool(signals.get("handle_in_source_title"))
    generic = generic_profile_like(row)
    accessible = bool(row.get("accessible"))

    if not accessible:
        decision = "reject_unreachable_or_blocked"
        reason = "public follow-up URL was blocked or unreachable"
    elif not subject:
        decision = "needs_subject_context_before_identity_review"
        reason = "source/profile content is accessible, but the adjudicated row has no subject context"
    elif generic:
        decision = "reject_generic_or_third_party_profile_index"
        reason = "profile page looks like a generic platform/index/false-positive page"
    elif subject_in_profile and subject_in_source:
        decision = "candidate_direct_text_needs_human_identity_review"
        reason = "subject appears in both source context and compact profile evidence, but graph acceptance remains gated"
    elif subject_in_profile or handle_in_profile or handle_in_source:
        decision = "needs_stronger_source_backed_identity_text"
        reason = "only partial subject/handle evidence is present"
    else:
        decision = "reject_no_identity_text_match"
        reason = "accessible profile evidence does not match subject context"

    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "reviewed_at": now_iso(),
        "row_index": row.get("row_index"),
        "adjudication_bucket": first_text(row.get("adjudication_bucket")),
        "source_family": first_text(row.get("source_family")),
        "source_article_uid": first_text(row.get("source_article_uid")),
        "source_title": source_title,
        "subject_name": subject,
        "url": first_text(row.get("url")),
        "final_url": first_text(row.get("final_url")),
        "status_code": row.get("status_code"),
        "followup_status": first_text(row.get("followup_status")),
        "review_gate_decision": decision,
        "review_gate_reason": reason,
        "generic_profile_like": generic,
        "signals": {
            "subject_in_profile_text": subject_in_profile,
            "subject_in_source_title": subject_in_source,
            "handle_in_profile_text": handle_in_profile,
            "handle_in_source_title": handle_in_source,
        },
        "accepted_for_graph": False,
        "identity_proof": False,
        "graph_write_allowed": False,
    }


def build_review_gate(*, review_paths: list[Path], out_dir: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    input_rows: list[dict[str, Any]] = []
    for path in review_paths:
        input_rows.extend(read_jsonl(path))
    reviewed_rows = [review_row(row) for row in input_rows]
    accepted_rows: list[dict[str, Any]] = []
    status_counts = Counter(row["review_gate_decision"] for row in reviewed_rows)
    bucket_counts = Counter(row["adjudication_bucket"] for row in reviewed_rows)

    out_dir.mkdir(parents=True, exist_ok=True)
    review_path = out_dir / "source_followup_review_gate.jsonl"
    rejected_path = out_dir / "rejected_or_needs_more_source.jsonl"
    accepted_path = out_dir / "accepted_external_identity_edges_for_graph.jsonl"
    write_jsonl(review_path, reviewed_rows)
    write_jsonl(rejected_path, reviewed_rows)
    write_jsonl(accepted_path, accepted_rows)

    candidate_direct_text_rows = status_counts.get("candidate_direct_text_needs_human_identity_review", 0)
    needs_more_source_rows = sum(
        count for key, count in status_counts.items() if key.startswith("needs_") or key.startswith("candidate_")
    )
    rejected_rows = len(reviewed_rows) - needs_more_source_rows
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "external_identity_source_followup_review_gate_ready_no_graph_acceptance",
        "review_paths": [str(path) for path in review_paths],
        "review_path": str(review_path),
        "rejected_or_needs_more_source_path": str(rejected_path),
        "accepted_edges_path": str(accepted_path),
        "input_rows": len(input_rows),
        "reviewed_rows": len(reviewed_rows),
        "candidate_direct_text_rows": candidate_direct_text_rows,
        "needs_more_source_rows": needs_more_source_rows,
        "rejected_rows": rejected_rows,
        "accepted_for_graph": 0,
        "status_counts": dict(status_counts),
        "bucket_counts": dict(bucket_counts),
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
    write_json(out_dir / "source_followup_review_gate_summary.json", summary)
    write_markdown(out_dir / "source_followup_review_gate_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# External Identity Source Follow-Up Review Gate",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- input_rows: `{summary['input_rows']}`",
        f"- reviewed_rows: `{summary['reviewed_rows']}`",
        f"- candidate_direct_text_rows: `{summary['candidate_direct_text_rows']}`",
        f"- needs_more_source_rows: `{summary['needs_more_source_rows']}`",
        f"- rejected_rows: `{summary['rejected_rows']}`",
        f"- accepted_for_graph: `{summary['accepted_for_graph']}`",
        f"- review_path: `{summary['review_path']}`",
        f"- accepted_edges_path: `{summary['accepted_edges_path']}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in sorted(summary["status_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Bucket Counts", ""])
    for key, value in sorted(summary["bucket_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only review gate.",
            "- No network calls.",
            "- No graph/vector/DB/mem0 writes.",
            "- Accepted graph edge output remains empty.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", action="append", type=Path, default=[], help="Source follow-up review JSONL; may repeat.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    review_paths = args.review or DEFAULT_FOLLOWUP_REVIEWS
    summary = build_review_gate(review_paths=review_paths, out_dir=args.out_dir)
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "reviewed_rows": summary["reviewed_rows"],
                "needs_more_source_rows": summary["needs_more_source_rows"],
                "rejected_rows": summary["rejected_rows"],
                "accepted_for_graph": summary["accepted_for_graph"],
                "summary": str(args.out_dir / "source_followup_review_gate_summary.json"),
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

