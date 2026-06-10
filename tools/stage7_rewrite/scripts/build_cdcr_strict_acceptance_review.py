#!/usr/bin/env python3
"""Build strict report-only CDCR direct-source acceptance rows.

This gate accepts only subjects with multiple accessible direct-source rows,
including at least one artist/profile source. It does not browse or write graph
state; accepted rows are staging-review evidence for a future Neo4j write gate.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_EVIDENCE = Path("reports/p1_cdcr_direct_source_20260515/cdcr_direct_evidence.jsonl")
DEFAULT_OUT_DIR = Path("reports/cdcr_strict_acceptance_review_20260517")
SCHEMA_VERSION = "stage7_cdcr_strict_acceptance_review.v1"
GATE_ID = "stage7_prd02_cdcr_strict_multi_source_profile_20260517"
PROFILE_SOURCE_TYPES = {"artist_profile", "bandcamp_artist"}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for CDCR strict acceptance: {path}")


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


def accepted_subject_row(subject: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    direct = [
        row
        for row in rows
        if row.get("accessible")
        and row.get("direct_source_candidate")
        and first_text(row.get("match_type")) == "name_context_match"
        and float(row.get("confidence") or 0) >= 0.8
    ]
    source_types = Counter(first_text(row.get("source_type")) for row in direct)
    profile_rows = [row for row in direct if first_text(row.get("source_type")) in PROFILE_SOURCE_TYPES]
    if len(direct) < 2 or not profile_rows:
        return None
    best_profile = profile_rows[0]
    return {
        "schema_version": SCHEMA_VERSION + ".accepted_row",
        "acceptance_gate_id": GATE_ID,
        "subject_name": subject,
        "accepted_for_graph": True,
        "accepted_for_staging": True,
        "graph_ready": True,
        "identity_proof": True,
        "proof_tier": "strict_multi_source_profile_identity",
        "review_status": "accepted_for_staging",
        "review_reason": "Subject has multiple accessible direct-source rows and at least one artist/profile source.",
        "primary_profile_url": first_text(best_profile.get("final_url") or best_profile.get("source_url")),
        "primary_profile_source_type": first_text(best_profile.get("source_type")),
        "source_urls": [first_text(row.get("final_url") or row.get("source_url")) for row in direct],
        "source_types": dict(source_types),
        "evidence_rows": len(direct),
        "staging_only": True,
        "write_allowed": False,
        "rollback_key": GATE_ID,
    }


def build_review(*, evidence_path: Path, out_dir: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    rows = read_jsonl(evidence_path)
    by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        subject = first_text(row.get("subject_name"))
        if subject:
            by_subject[subject].append(row)

    accepted_rows = []
    review_rows = []
    for subject, subject_rows in sorted(by_subject.items()):
        accepted = accepted_subject_row(subject, subject_rows)
        direct_count = sum(1 for row in subject_rows if row.get("direct_source_candidate"))
        profile_count = sum(
            1 for row in subject_rows if row.get("direct_source_candidate") and first_text(row.get("source_type")) in PROFILE_SOURCE_TYPES
        )
        review = {
            "schema_version": SCHEMA_VERSION + ".review_row",
            "subject_name": subject,
            "candidate_rows": len(subject_rows),
            "direct_source_candidates": direct_count,
            "profile_source_candidates": profile_count,
            "accepted_for_graph": bool(accepted),
            "review_decision": "accepted_strict_multi_source_profile" if accepted else "not_accepted_strict_gate",
        }
        review_rows.append(review)
        if accepted:
            accepted_rows.append(accepted)

    out_dir.mkdir(parents=True, exist_ok=True)
    review_path = out_dir / "cdcr_strict_acceptance_review.jsonl"
    accepted_path = out_dir / "accepted_cdcr_graph_edges_strict.jsonl"
    write_jsonl(review_path, review_rows)
    write_jsonl(accepted_path, accepted_rows)
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "cdcr_strict_acceptance_ready" if accepted_rows else "cdcr_strict_acceptance_no_rows_accepted",
        "acceptance_gate_id": GATE_ID,
        "evidence_path": str(evidence_path),
        "review_path": str(review_path),
        "accepted_edges_path": str(accepted_path),
        "subject_count": len(by_subject),
        "review_rows": len(review_rows),
        "accepted_edges": len(accepted_rows),
        "accepted_subjects": [row["subject_name"] for row in accepted_rows],
        "blockers": [
            "accepted rows are report-only and require a separate Neo4j staging write gate before graph use",
            "production graph labels remain forbidden",
            "subjects rejected by the strict policy remain review candidates only",
        ],
        "safety": {
            "reports_only": True,
            "existing_evidence_only": True,
            "no_network_calls": True,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
            "publish_executed": False,
        },
        "writes": "reports_only",
    }
    write_json(out_dir / "cdcr_strict_acceptance_review.json", packet)
    write_markdown(out_dir / "cdcr_strict_acceptance_review.md", packet)
    return packet


def write_markdown(path: Path, packet: dict[str, Any]) -> None:
    lines = [
        "# CDCR Strict Acceptance Review",
        "",
        f"- generated_at: `{packet['generated_at']}`",
        f"- decision: `{packet['decision']}`",
        f"- subject_count: `{packet['subject_count']}`",
        f"- review_rows: `{packet['review_rows']}`",
        f"- accepted_edges: `{packet['accepted_edges']}`",
        "",
        "## Accepted Subjects",
        "",
    ]
    if packet["accepted_subjects"]:
        lines.extend(f"- {item}" for item in packet["accepted_subjects"])
    else:
        lines.append("- none")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(packet["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    packet = build_review(evidence_path=args.evidence, out_dir=args.out_dir)
    print(
        json.dumps(
            {
                "ok": packet["ok"],
                "decision": packet["decision"],
                "subject_count": packet["subject_count"],
                "accepted_edges": packet["accepted_edges"],
                "accepted_subjects": packet["accepted_subjects"],
                "summary": str(args.out_dir / "cdcr_strict_acceptance_review.json"),
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
