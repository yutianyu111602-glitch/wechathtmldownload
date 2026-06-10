#!/usr/bin/env python3
"""Build a report-only PRD-02/PRD-16 social identity acceptance gate packet.

The packet consolidates CDCR direct-source review, deterministic social identity
review, and OpenCLI rendered-profile review into one acceptance checklist. It
does not accept any edge automatically, does not browse, does not log in, and
does not write Neo4j or other production state.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_CDCR_REVIEW = Path("reports/p1_cdcr_direct_source_review_20260516/cdcr_direct_source_review_summary.json")
DEFAULT_CDCR_STRICT_ACCEPTANCE = Path(
    "reports/cdcr_strict_acceptance_review_20260517/cdcr_strict_acceptance_review.json"
)
DEFAULT_SOCIAL_REVIEW = Path(
    "reports/social_identity_cross_evidence_20260515/identity_cross_evidence_summary.json"
)
DEFAULT_OPENCLI_REVIEW = Path("reports/opencli_social_identity_review_20260516/opencli_identity_review_summary.json")
DEFAULT_STRICT_ACCEPTANCE = Path(
    "reports/social_identity_strict_acceptance_review_20260517/social_identity_strict_acceptance_review.json"
)
DEFAULT_GRAPH_PROMOTION = Path("reports/graph_promotion_readiness_refresh_20260516/graph_promotion_readiness.json")
DEFAULT_OUT_DIR = Path("reports/social_identity_acceptance_gate_packet_20260517")
SCHEMA_VERSION = "stage7_social_identity_acceptance_gate_packet.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for social identity acceptance gate: {path}")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return value if isinstance(value, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def unique_nonempty(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def build_packet(
    *,
    cdcr_review_path: Path,
    cdcr_strict_acceptance_path: Path = DEFAULT_CDCR_STRICT_ACCEPTANCE,
    social_review_path: Path,
    opencli_review_path: Path,
    strict_acceptance_path: Path = DEFAULT_STRICT_ACCEPTANCE,
    graph_promotion_path: Path,
    out_dir: Path,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    cdcr = read_json(cdcr_review_path)
    cdcr_strict = read_json(cdcr_strict_acceptance_path)
    social = read_json(social_review_path)
    opencli = read_json(opencli_review_path)
    strict = read_json(strict_acceptance_path)
    graph = read_json(graph_promotion_path)
    accepted_edges_total = (
        int(cdcr.get("accepted_edges") or 0)
        + int(cdcr_strict.get("accepted_edges") or 0)
        + int(social.get("accepted_edges") or 0)
        + int(opencli.get("accepted_edges") or 0)
        + int(strict.get("accepted_edges") or 0)
    )
    review_candidates_total = (
        int(cdcr.get("direct_source_candidates") or 0)
        + int(cdcr.get("source_backed_profile_review_candidates") or 0)
        + int(social.get("strong_review_candidates") or 0)
        + int(social.get("medium_review_candidates") or 0)
        + int(opencli.get("strong_opencli_review_candidates") or 0)
        + int(opencli.get("medium_opencli_review_candidates") or 0)
    )
    local_ready_gates = {
        "cdcr_review_ready": cdcr.get("decision") == "cdcr_direct_source_review_ready",
        "cdcr_strict_acceptance_ready": cdcr_strict.get("decision")
        in {"cdcr_strict_acceptance_ready", "cdcr_strict_acceptance_no_rows_accepted"},
        "social_identity_review_ready": social.get("decision") == "social_identity_cross_evidence_review_ready",
        "opencli_identity_review_ready": opencli.get("decision") == "opencli_identity_review_ready",
        "review_candidates_present": review_candidates_total > 0,
        "accepted_edges_empty": accepted_edges_total == 0,
        "graph_blocker_recorded": bool(graph.get("blockers")) and not bool(graph.get("promotion_allowed")),
        "no_unsafe_reject_rows": int(opencli.get("unsafe_reject_rows") or 0) == 0,
        "strict_acceptance_review_ready": strict.get("decision")
        in {"social_identity_strict_acceptance_ready", "social_identity_strict_acceptance_no_rows_accepted"},
    }
    hard_gate_seed = []
    if accepted_edges_total == 0:
        hard_gate_seed.extend(
            [
                "source-backed identity acceptance gate is required before any edge can be accepted",
                "accepted_edges remains 0 across CDCR/social/OpenCLI reviews",
            ]
        )
    else:
        hard_gate_seed.append("accepted strict identity rows require a separate Neo4j staging write gate before graph use")
    hard_gate_seed.extend(
        [
            "Neo4j staging write is forbidden for identity candidates in this run",
            "production graph labels are forbidden for this run",
            "PRD-07 graph promotion is blocked",
            "OpenCLI rendered evidence is review context unless strict acceptance criteria are met",
            "CDCR evidence is review-ready but not identity proof",
            "do not perform social account actions or private/follower-only collection",
        ]
    )
    hard_gates_remaining = unique_nonempty(hard_gate_seed)
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "social_identity_acceptance_gate_packet_ready_report_only",
        "cdcr_review_path": str(cdcr_review_path),
        "cdcr_strict_acceptance_path": str(cdcr_strict_acceptance_path),
        "social_review_path": str(social_review_path),
        "opencli_review_path": str(opencli_review_path),
        "strict_acceptance_path": str(strict_acceptance_path),
        "graph_promotion_path": str(graph_promotion_path),
        "accepted_edges_total": accepted_edges_total,
        "accepted_edges_by_scope": {
            "cdcr": int(cdcr.get("accepted_edges") or 0),
            "cdcr_strict": int(cdcr_strict.get("accepted_edges") or 0),
            "social": int(social.get("accepted_edges") or 0),
            "opencli": int(opencli.get("accepted_edges") or 0),
            "strict_prd16": int(strict.get("accepted_edges") or 0),
            "strict_cdcr_subject_overlap": int(strict.get("cdcr_subject_overlap_accepted_count") or 0),
        },
        "review_candidates_total": review_candidates_total,
        "candidate_summary": {
            "cdcr_direct_source_candidates": cdcr.get("direct_source_candidates"),
            "cdcr_source_backed_profile_review_candidates": cdcr.get(
                "source_backed_profile_review_candidates"
            ),
            "cdcr_graph_ready_rows": cdcr.get("graph_ready_rows"),
            "cdcr_strict_accepted_edges": cdcr_strict.get("accepted_edges"),
            "cdcr_strict_accepted_subjects": cdcr_strict.get("accepted_subjects"),
            "social_strong_review_candidates": social.get("strong_review_candidates"),
            "social_medium_review_candidates": social.get("medium_review_candidates"),
            "opencli_strong_review_candidates": opencli.get("strong_opencli_review_candidates"),
            "opencli_medium_review_candidates": opencli.get("medium_opencli_review_candidates"),
            "opencli_rows_with_external_links": opencli.get("rows_with_external_links"),
            "strict_acceptance_review_rows": strict.get("review_rows"),
            "strict_accepted_edges": strict.get("accepted_edges"),
            "strict_accepted_subjects": strict.get("accepted_subjects"),
            "strict_cdcr_subject_overlap_accepted_count": strict.get("cdcr_subject_overlap_accepted_count"),
        },
        "accepted_edge_files": {
            "cdcr": cdcr.get("accepted_edges_path"),
            "cdcr_strict": cdcr_strict.get("accepted_edges_path"),
            "social": social.get("accepted_edges_path"),
            "opencli": opencli.get("accepted_edges_path"),
            "strict": strict.get("accepted_edges_path"),
        },
        "local_ready_gates": local_ready_gates,
        "local_ready_gate_count": sum(1 for value in local_ready_gates.values() if value),
        "hard_gates_remaining": hard_gates_remaining,
        "acceptance_policy_required": [
            "direct source must name the same subject and the same social/profile target",
            "string or rendered visibility evidence can support review but cannot accept alone",
            "accepted edge rows must include source URL, proof tier, reviewer or gate id, and rollback run id",
            "social account actions, cookie/token export, and private content collection remain forbidden",
        ],
        "forbidden_next_actions": [
            "do_not_auto_accept_edges_from_string_matches",
            "do_not_auto_accept_edges_from_logged_in_visibility",
            "do_not_export_cookie_or_token",
            "do_not_perform_social_account_actions",
            "do_not_collect_private_or_follower_only_content",
            "do_not_write_neo4j_from_identity_candidates",
        ],
        "allowed_next_actions": [
            "use candidate rows for a separate source-backed acceptance review",
            "keep accepted edge files empty until specific rows meet the acceptance policy",
            "use this packet as PRD-02/PRD-16 graph blocker evidence",
        ],
        "safety": {
            "reports_only": True,
            "no_network_calls": True,
            "no_login": True,
            "no_cookie_token_export": True,
            "no_account_action": True,
            "no_private_collection": True,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
            "publish_executed": False,
        },
        "writes": "reports_only",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "social_identity_acceptance_gate_packet.json", packet)
    write_markdown(out_dir / "social_identity_acceptance_gate_packet.md", packet)
    return packet


def write_markdown(path: Path, packet: dict[str, Any]) -> None:
    lines = [
        "# Social Identity Acceptance Gate Packet",
        "",
        f"- generated_at: `{packet['generated_at']}`",
        f"- decision: `{packet['decision']}`",
        f"- review_candidates_total: `{packet['review_candidates_total']}`",
        f"- accepted_edges_total: `{packet['accepted_edges_total']}`",
        f"- local_ready_gate_count: `{packet['local_ready_gate_count']}`",
        "",
        "## Hard Gates Remaining",
        "",
    ]
    for item in packet["hard_gates_remaining"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Candidate Summary", ""])
    for key, value in packet["candidate_summary"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(packet["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdcr-review", type=Path, default=DEFAULT_CDCR_REVIEW)
    parser.add_argument("--cdcr-strict-acceptance", type=Path, default=DEFAULT_CDCR_STRICT_ACCEPTANCE)
    parser.add_argument("--social-review", type=Path, default=DEFAULT_SOCIAL_REVIEW)
    parser.add_argument("--opencli-review", type=Path, default=DEFAULT_OPENCLI_REVIEW)
    parser.add_argument("--strict-acceptance", type=Path, default=DEFAULT_STRICT_ACCEPTANCE)
    parser.add_argument("--graph-promotion", type=Path, default=DEFAULT_GRAPH_PROMOTION)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    packet = build_packet(
        cdcr_review_path=args.cdcr_review,
        cdcr_strict_acceptance_path=args.cdcr_strict_acceptance,
        social_review_path=args.social_review,
        opencli_review_path=args.opencli_review,
        strict_acceptance_path=args.strict_acceptance,
        graph_promotion_path=args.graph_promotion,
        out_dir=args.out_dir,
    )
    print(
        json.dumps(
            {
                "ok": packet["ok"],
                "decision": packet["decision"],
                "review_candidates_total": packet["review_candidates_total"],
                "accepted_edges_total": packet["accepted_edges_total"],
                "hard_gates_remaining": len(packet["hard_gates_remaining"]),
                "summary": str(args.out_dir / "social_identity_acceptance_gate_packet.json"),
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
