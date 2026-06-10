#!/usr/bin/env python3
"""Build a report-only strict manual acceptance review for Atlas T6 identities.

This gate joins the T6 rendered public-profile evidence with the prior T5/T7
manual acceptance queue. It can mark rows as identity-staging accepted for the
next review packet, but it never promotes product truth or enables writes.
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
from urllib import parse


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_RENDERED_EVIDENCE = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_rendered_profile_evidence_q6_20260524_0328"
    / "atlas_social_rendered_profile_evidence.jsonl"
)
DEFAULT_MANUAL_QUEUE = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_identity_acceptance_gate_q6_20260524_0224"
    / "atlas_social_identity_manual_acceptance_review_queue.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_strict_manual_acceptance_q6_20260524"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_STRICT_MANUAL_ACCEPTANCE_REVIEW_PACKET_20260524.md"
SCHEMA_VERSION = "stage7_atlas_social_strict_manual_acceptance_review.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Q6 strict acceptance review: {path}")


def read_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    reject_d_path(path, label)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
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


def host_of(url: str) -> str:
    host = parse.urlparse(compact(url)).netloc.casefold()
    return host[4:] if host.startswith("www.") else host


def public_soundcloud_url(url: str) -> bool:
    parsed = parse.urlparse(compact(url))
    if parsed.scheme not in {"http", "https"}:
        return False
    return host_of(url) == "soundcloud.com" and bool(parsed.path.strip("/"))


def manual_by_entity(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = compact(row.get("entity_search_id"))
        if key and key not in result:
            result[key] = row
    return result


def evidence_signals(rendered: dict[str, Any], manual: dict[str, Any]) -> dict[str, bool]:
    rendered_signals = rendered.get("signals") if isinstance(rendered.get("signals"), dict) else {}
    target_url = compact(rendered.get("target_url") or rendered.get("canonical_url") or rendered.get("final_url"))
    return {
        "manual_gate_ready": compact(manual.get("acceptance_gate_status"))
        == "manual_acceptance_review_ready_without_identity_proof",
        "atlas_profile_found": bool(manual.get("atlas_profile_found")),
        "atlas_event_context_present": int(manual.get("atlas_event_count") or 0) > 0,
        "atlas_source_context_present": int(manual.get("atlas_source_article_count") or 0) > 0,
        "rendered_profile_ready": compact(rendered.get("decision")) == "rendered_profile_evidence_review_ready",
        "no_opencli_error": not compact(rendered.get("opencli_error")),
        "public_soundcloud_profile_url": public_soundcloud_url(target_url),
        "canonical_or_final_url_matches_candidate": bool(rendered_signals.get("canonical_or_final_url_matches_candidate")),
        "rendered_profile_metadata_present": bool(rendered_signals.get("rendered_profile_metadata_present")),
        "subject_in_rendered_public_profile": bool(rendered_signals.get("subject_in_rendered_public_profile")),
        "profile_image_hash_present": compact(rendered.get("profile_image_url_or_hash")).startswith("sha256:"),
        "previous_product_truth_not_promoted": not bool(rendered.get("accepted_for_graph"))
        and not bool(rendered.get("identity_proof"))
        and not bool(rendered.get("identity_proof_promoted")),
    }


def build_review_row(rendered: dict[str, Any], manual: dict[str, Any], generated_at: str) -> dict[str, Any]:
    signals = evidence_signals(rendered, manual)
    accepted = all(signals.values())
    entity = compact(rendered.get("entity_search_id") or manual.get("entity_search_id"))
    name = compact(rendered.get("name") or rendered.get("atlas_display_name") or manual.get("name"))
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "entity_search_id": entity,
        "name": name,
        "atlas_dj_id": compact(rendered.get("atlas_dj_id") or manual.get("atlas_dj_id")),
        "atlas_display_name": compact(rendered.get("atlas_display_name") or manual.get("atlas_display_name")),
        "target_url": compact(rendered.get("target_url") or rendered.get("canonical_url") or rendered.get("final_url")),
        "profile_image_url_or_hash": compact(rendered.get("profile_image_url_or_hash")),
        "description_excerpt": compact(rendered.get("description_excerpt"), 300),
        "atlas_event_count": int(manual.get("atlas_event_count") or 0),
        "atlas_source_article_count": int(manual.get("atlas_source_article_count") or 0),
        "rendered_evidence_decision": compact(rendered.get("decision")),
        "signals": signals,
        "strict_manual_acceptance_passed": accepted,
        "manual_acceptance_decision": (
            "identity_candidate_accepted_for_staging_review"
            if accepted
            else "identity_candidate_rejected_or_needs_more_evidence"
        ),
        "review_reason": (
            "Atlas source context and rendered public SoundCloud profile evidence both satisfy this report-only acceptance gate."
            if accepted
            else "Strict manual acceptance requirements were not fully met."
        ),
        "accepted_for_graph": False,
        "identity_proof": False,
        "identity_proof_promoted": False,
        "avatar_display_allowed": False,
        "public_serving_field_allowed": False,
        "graph_write_allowed": False,
        "next_gate": "Build a separate graph/write gate before any serving, Neo4j, Qdrant, SQLite, avatar, public field, or memory mutation.",
    }


def build_review(*, rendered_evidence_path: Path, manual_queue_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    generated_at = now_iso()
    rendered_rows = read_jsonl(rendered_evidence_path, "rendered_evidence")
    manual_rows = read_jsonl(manual_queue_path, "manual_queue")
    manual_lookup = manual_by_entity(manual_rows)

    review_rows = [
        build_review_row(row, manual_lookup.get(compact(row.get("entity_search_id")), {}), generated_at)
        for row in rendered_rows
    ]
    accepted_rows = [row for row in review_rows if row["strict_manual_acceptance_passed"]]
    blocked_rows = [row for row in review_rows if not row["strict_manual_acceptance_passed"]]
    decision_counts = Counter(row["manual_acceptance_decision"] for row in review_rows)

    review_path = out_dir / "atlas_social_strict_manual_acceptance_review.jsonl"
    accepted_path = out_dir / "atlas_social_strict_manual_acceptance_ready.jsonl"
    blocked_path = out_dir / "atlas_social_strict_manual_acceptance_blocked.jsonl"
    summary_path = out_dir / "atlas_social_strict_manual_acceptance_summary.json"
    write_jsonl(review_path, review_rows)
    write_jsonl(accepted_path, accepted_rows)
    write_jsonl(blocked_path, blocked_rows)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "ok": True,
        "decision": (
            "atlas_social_strict_manual_acceptance_ready_report_only"
            if accepted_rows and not blocked_rows
            else "atlas_social_strict_manual_acceptance_partial_or_blocked_report_only"
        ),
        "rendered_evidence_path": str(rendered_evidence_path),
        "manual_queue_path": str(manual_queue_path),
        "out_dir": str(out_dir),
        "report_path": str(report_path),
        "review_path": str(review_path),
        "accepted_path": str(accepted_path),
        "blocked_path": str(blocked_path),
        "rendered_rows": len(rendered_rows),
        "manual_queue_rows": len(manual_rows),
        "strict_manual_acceptance_passed": len(accepted_rows),
        "blocked_rows": len(blocked_rows),
        "accepted_entities": [row["name"] for row in accepted_rows],
        "decision_counts": dict(sorted(decision_counts.items())),
        "accepted_for_graph": 0,
        "identity_proof_promoted": 0,
        "avatar_display_allowed": 0,
        "public_serving_field_allowed": 0,
        "graph_write_allowed": 0,
        "next_gate": "Separate graph/write gate is still required before production serving, Neo4j, Qdrant, SQLite, avatar display, public fields, or memory writes.",
        "safety": {
            "report_only": True,
            "network_call_executed": False,
            "model_call_executed": False,
            "paid_api_used": False,
            "page_body_persisted": False,
            "graph_write_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "secret_value_read_or_printed": False,
            "d_scan_executed": False,
        },
    }
    write_json(summary_path, summary)
    write_markdown(out_dir / "atlas_social_strict_manual_acceptance_summary.md", summary, review_rows)
    write_markdown(report_path, summary, review_rows, top_level=True)
    return summary


def write_markdown(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]], top_level: bool = False) -> None:
    title = "Atlas T6 Strict Manual Acceptance Review Packet" if top_level else "Atlas Social Strict Manual Acceptance"
    lines = [
        f"# {title}",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- rendered_rows: `{summary['rendered_rows']}`",
        f"- manual_queue_rows: `{summary['manual_queue_rows']}`",
        f"- strict_manual_acceptance_passed: `{summary['strict_manual_acceptance_passed']}`",
        f"- blocked_rows: `{summary['blocked_rows']}`",
        f"- accepted_for_graph: `{summary['accepted_for_graph']}`",
        f"- identity_proof_promoted: `{summary['identity_proof_promoted']}`",
        f"- avatar_display_allowed: `{summary['avatar_display_allowed']}`",
        f"- public_serving_field_allowed: `{summary['public_serving_field_allowed']}`",
        f"- graph_write_allowed: `{summary['graph_write_allowed']}`",
        f"- review_path: `{summary['review_path']}`",
        f"- accepted_path: `{summary['accepted_path']}`",
        f"- blocked_path: `{summary['blocked_path']}`",
        "",
        "## Accepted Entities",
        "",
    ]
    for entity in summary["accepted_entities"]:
        lines.append(f"- `{entity}`")
    if not summary["accepted_entities"]:
        lines.append("- none")
    lines.extend(["", "## Review Rows", ""])
    for row in rows:
        lines.append(
            "- `{name}` `{entity}`: decision `{decision}`, events `{events}`, source_articles `{articles}`, target `{target}`".format(
                name=row["name"],
                entity=row["entity_search_id"],
                decision=row["manual_acceptance_decision"],
                events=row["atlas_event_count"],
                articles=row["atlas_source_article_count"],
                target=row["target_url"],
            )
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only gate; no network/model/API call was executed by this script.",
            "- No product truth, identity proof promotion, avatar display, public serving field, graph/vector/DB write, or memory write was enabled.",
            "- This packet only prepares accepted identity candidates for a later separate graph/write gate.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rendered-evidence", type=Path, default=DEFAULT_RENDERED_EVIDENCE)
    parser.add_argument("--manual-queue", type=Path, default=DEFAULT_MANUAL_QUEUE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_review(
        rendered_evidence_path=args.rendered_evidence,
        manual_queue_path=args.manual_queue,
        out_dir=args.out_dir,
        report_path=args.report,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
