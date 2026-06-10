#!/usr/bin/env python3
"""Build a report-only DB3 DJ identity review workbench.

Consumes the S64 identity merge packet and turns unsafe merge candidates into
review rows with risk reasons. This script writes evidence only; it does not
mutate DB1/DB2/DB3 or authorize any identity merge.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MERGE_PACKET = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_merge_packet_s64_20260531"
    / "atlas_dj_identity_merge_packet.json"
)
DEFAULT_OUT_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "atlas_dj_identity_review_workbench_s73_20260531"


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def score_sum(candidate: dict[str, Any], field: str) -> int:
    total = 0
    for row in candidate.get("scores", []):
        if isinstance(row, dict):
            total += int(row.get(field) or 0)
    return total


def max_score(candidate: dict[str, Any], field: str) -> int:
    values = [int(row.get(field) or 0) for row in candidate.get("scores", []) if isinstance(row, dict)]
    return max(values or [0])


def token_text(candidate: dict[str, Any]) -> str:
    return str(candidate.get("identity_token") or "").strip().lower()


def classify_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    token = token_text(candidate)
    merge_count = len(candidate.get("merge_dj_ids") or [])
    all_count = len(candidate.get("all_dj_ids") or [])
    total_events = score_sum(candidate, "event_rows")
    total_collaborators = score_sum(candidate, "collaborator_edges")
    total_venues = score_sum(candidate, "venue_rows")
    reason_codes: list[str] = []

    if not str(candidate.get("city_key") or "").strip():
        reason_codes.append("missing_city_key")
    if re.search(r"\d+\s*位|多位|国内外|嘉宾|阵容|lineup|artists?", token, re.I):
        reason_codes.append("collective_or_lineup_label")
    if len(re.sub(r"\s+", "", token)) <= 2:
        reason_codes.append("short_identity_token")
    if merge_count >= 2:
        reason_codes.append("multiple_merge_ids")
    if max_score(candidate, "event_rows") >= 10 or total_events >= 10:
        reason_codes.append("high_evidence_canonical_candidate")
    if total_collaborators > 0:
        reason_codes.append("has_collaborator_edges")
    if total_venues > 0:
        reason_codes.append("has_venue_history")

    high_risk_reasons = {"collective_or_lineup_label", "short_identity_token"}
    if high_risk_reasons.intersection(reason_codes):
        risk_level = "high"
    elif merge_count >= 2 or total_events >= 10 or total_collaborators > 0:
        risk_level = "medium"
    else:
        risk_level = "low"

    priority_score = (
        (1000 if risk_level == "high" else 500 if risk_level == "medium" else 100)
        + total_events * 5
        + total_collaborators * 3
        + total_venues * 2
        + all_count
    )
    return {
        "group_id": candidate.get("group_id", ""),
        "identity_token": candidate.get("identity_token", ""),
        "city_key": candidate.get("city_key", ""),
        "canonical_dj_id": candidate.get("canonical_dj_id", ""),
        "merge_dj_ids": candidate.get("merge_dj_ids", []),
        "all_dj_ids": candidate.get("all_dj_ids", []),
        "display_names": candidate.get("display_names", []),
        "normalized_names": candidate.get("normalized_names", []),
        "row_count": candidate.get("row_count", 0),
        "risk_level": risk_level,
        "priority_score": priority_score,
        "reason_codes": reason_codes,
        "total_event_rows": total_events,
        "total_collaborator_edges": total_collaborators,
        "total_venue_rows": total_venues,
        "review_required": True,
        "safe_automerge": False,
        "database_write_allowed": False,
        "recommended_action": "manual_identity_review_before_any_write_gate",
    }


def build_workbench(packet: dict[str, Any], *, source_packet: Path, top_limit: int) -> dict[str, Any]:
    candidates = packet.get("candidates", []) if isinstance(packet.get("candidates"), list) else []
    rows = [classify_candidate(candidate) for candidate in candidates if isinstance(candidate, dict)]
    rows.sort(key=lambda row: (-int(row["priority_score"]), str(row["group_id"])))

    risk_counts = Counter(row["risk_level"] for row in rows)
    reason_counts = Counter(reason for row in rows for reason in row["reason_codes"])
    return {
        "schema_version": "atlas_dj_identity_review_workbench.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "decision": "atlas_dj_identity_review_workbench_ready_report_only",
        "source_merge_packet": rel(source_packet),
        "source_candidate_count": int(packet.get("candidate_count") or len(candidates)),
        "source_merge_id_count": int(packet.get("merge_id_count") or 0),
        "review_row_count": len(rows),
        "top_limit": top_limit,
        "risk_counts": dict(sorted(risk_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "safe_automerge_allowed": False,
        "database_write_allowed": False,
        "top_review_rows": rows[:top_limit],
        "review_rows": rows,
        "rules": [
            "Every row is manual-review only; safe_automerge and database_write_allowed stay false.",
            "Collective/lineup labels and very short identity tokens are high risk.",
            "High evidence coverage can help choose a canonical id but does not authorize a write.",
            "Future write gates must preserve non-empty event, venue, collaborator, source_ref, mixtape, social, bio, avatar, and evidence fields.",
        ],
        "safety": {
            "report_only": True,
            "database_mutations": False,
            "identity_merge_executed": False,
            "source_mutations": False,
            "provider_or_llm_call": False,
            "secret_read": False,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Atlas DJ Identity Review Workbench",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Source merge packet: `{report['source_merge_packet']}`",
        f"- Review rows: `{report['review_row_count']}`",
        f"- Source candidate count: `{report['source_candidate_count']}`",
        f"- Source merge id count: `{report['source_merge_id_count']}`",
        "",
        "## Risk Counts",
    ]
    for key, value in report["risk_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Reason Counts"])
    for key, value in report["reason_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Top Review Rows"])
    for row in report["top_review_rows"]:
        lines.append(
            f"- `{row['risk_level']}` `{row['group_id']}` canonical `{row['canonical_dj_id']}` "
            f"merge `{len(row['merge_dj_ids'])}` reason `{','.join(row['reason_codes'])}`"
        )
    lines.extend(
        [
            "",
            "## Safety Boundary",
            "",
            "- No DB writes.",
            "- No identity merge executed.",
            "- No source mutation.",
            "- No provider, LLM, deploy, upload, review, restart, or secret read.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_outputs(out_dir: Path, report: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "atlas_dj_identity_review_workbench.json", report)
    write_jsonl(out_dir / "atlas_dj_identity_review_rows.jsonl", report["review_rows"])
    write_markdown(out_dir / "atlas_dj_identity_review_workbench.md", report)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build report-only DB3 DJ identity review workbench")
    parser.add_argument("--merge-packet", type=Path, default=DEFAULT_MERGE_PACKET)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--top-limit", type=int, default=50)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packet = read_json(args.merge_packet)
    report = build_workbench(packet, source_packet=args.merge_packet, top_limit=args.top_limit)
    write_outputs(args.out_dir, report)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "review_row_count": report["review_row_count"],
                "risk_counts": report["risk_counts"],
                "json": str(args.out_dir / "atlas_dj_identity_review_workbench.json"),
                "jsonl": str(args.out_dir / "atlas_dj_identity_review_rows.jsonl"),
                "markdown": str(args.out_dir / "atlas_dj_identity_review_workbench.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

