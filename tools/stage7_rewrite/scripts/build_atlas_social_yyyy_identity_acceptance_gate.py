#!/usr/bin/env python3
"""Build report-only identity acceptance gate for the YYYY follow-up row.

This gate joins the new YYYY source-context acceptance row with the rendered
SoundCloud profile evidence row. It only marks the row as staging-review ready;
all product/public/write gates remain closed.
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
DEFAULT_SOURCE_ACCEPTED = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_blocked_source_context_acceptance_q6_20260525"
    / "atlas_social_blocked_source_context_acceptance_ready.jsonl"
)
DEFAULT_RENDERED_EVIDENCE = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_rendered_profile_evidence_yyyy_q6_20260525_0555"
    / "atlas_social_rendered_profile_evidence.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_yyyy_identity_acceptance_q6_20260525"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_YYYY_IDENTITY_ACCEPTANCE_GATE_20260525.md"
SCHEMA_VERSION = "stage7_atlas_social_yyyy_identity_acceptance_gate.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for YYYY identity acceptance gate: {path}")


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
    return parsed.scheme in {"http", "https"} and host_of(url) == "soundcloud.com" and bool(parsed.path.strip("/"))


def by_entity(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        entity = compact(row.get("entity_search_id"))
        if entity and entity not in result:
            result[entity] = row
    return result


def build_row(source_row: dict[str, Any], rendered_row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    rendered_signals = rendered_row.get("signals") if isinstance(rendered_row.get("signals"), dict) else {}
    target_url = compact(rendered_row.get("target_url") or rendered_row.get("canonical_url") or rendered_row.get("final_url"))
    exact_events = int(source_row.get("exact_event_count") or 0)
    exact_sources = int(source_row.get("exact_source_article_count") or 0)
    signals = {
        "manual_source_context_accepted": compact(source_row.get("manual_source_context_decision"))
        == "manual_source_context_accepted_for_identity_review",
        "exact_atlas_event_context_present": exact_events > 0,
        "exact_atlas_source_context_present": exact_sources > 0,
        "rendered_profile_ready": compact(rendered_row.get("decision")) == "rendered_profile_evidence_review_ready",
        "no_opencli_error": not compact(rendered_row.get("opencli_error")),
        "public_soundcloud_profile_url": public_soundcloud_url(target_url),
        "canonical_or_final_url_matches_candidate": bool(rendered_signals.get("canonical_or_final_url_matches_candidate")),
        "rendered_profile_metadata_present": bool(rendered_signals.get("rendered_profile_metadata_present")),
        "subject_in_rendered_public_profile": bool(rendered_signals.get("subject_in_rendered_public_profile")),
        "profile_image_hash_present": compact(rendered_row.get("profile_image_url_or_hash")).startswith("sha256:"),
        "previous_product_truth_not_promoted": not bool(source_row.get("accepted_for_graph"))
        and not bool(source_row.get("identity_proof"))
        and not bool(source_row.get("identity_proof_promoted"))
        and not bool(rendered_row.get("accepted_for_graph"))
        and not bool(rendered_row.get("identity_proof"))
        and not bool(rendered_row.get("identity_proof_promoted")),
    }
    accepted = all(signals.values())
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "entity_search_id": compact(source_row.get("entity_search_id") or rendered_row.get("entity_search_id")),
        "name": compact(source_row.get("name") or rendered_row.get("name")),
        "type": compact(source_row.get("type")),
        "target_url": target_url,
        "canonical_url": compact(rendered_row.get("canonical_url")),
        "profile_image_url_or_hash": compact(rendered_row.get("profile_image_url_or_hash")),
        "description_excerpt": compact(rendered_row.get("description_excerpt"), 300),
        "exact_event_count": exact_events,
        "exact_source_article_count": exact_sources,
        "accepted_source_articles": source_row.get("accepted_source_articles") if isinstance(source_row.get("accepted_source_articles"), list) else [],
        "accepted_event_keys": source_row.get("accepted_event_keys") if isinstance(source_row.get("accepted_event_keys"), list) else [],
        "rendered_evidence_decision": compact(rendered_row.get("decision")),
        "signals": signals,
        "identity_acceptance_passed": accepted,
        "identity_acceptance_decision": (
            "identity_candidate_accepted_for_staging_review"
            if accepted
            else "identity_candidate_rejected_or_needs_more_evidence"
        ),
        "review_reason": (
            "Exact Atlas source context and rendered public SoundCloud profile evidence both satisfy this report-only gate."
            if accepted
            else "Strict YYYY identity acceptance requirements were not fully met."
        ),
        "accepted_for_graph": False,
        "identity_proof": False,
        "identity_proof_promoted": False,
        "avatar_display_allowed": False,
        "public_serving_field_allowed": False,
        "graph_write_allowed": False,
        "next_gate": "Build a separate graph/write gate before serving, Neo4j, Qdrant, SQLite, avatar, public field, or memory mutation.",
    }


def build_gate(*, source_accepted_path: Path, rendered_evidence_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    reject_d_path(report_path, "report_path")
    generated_at = now_iso()
    source_rows = read_jsonl(source_accepted_path, "source_accepted")
    rendered_rows = read_jsonl(rendered_evidence_path, "rendered_evidence")
    rendered_lookup = by_entity(rendered_rows)
    review_rows = [
        build_row(row, rendered_lookup.get(compact(row.get("entity_search_id")), {}), generated_at)
        for row in source_rows
    ]
    accepted_rows = [row for row in review_rows if row["identity_acceptance_passed"]]
    blocked_rows = [row for row in review_rows if not row["identity_acceptance_passed"]]
    decision_counts = Counter(row["identity_acceptance_decision"] for row in review_rows)

    review_path = out_dir / "atlas_social_yyyy_identity_acceptance_review.jsonl"
    accepted_path = out_dir / "atlas_social_yyyy_identity_acceptance_ready.jsonl"
    blocked_path = out_dir / "atlas_social_yyyy_identity_acceptance_blocked.jsonl"
    summary_path = out_dir / "atlas_social_yyyy_identity_acceptance_summary.json"
    write_jsonl(review_path, review_rows)
    write_jsonl(accepted_path, accepted_rows)
    write_jsonl(blocked_path, blocked_rows)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "ok": True,
        "decision": (
            "atlas_social_yyyy_identity_acceptance_ready_report_only"
            if accepted_rows and not blocked_rows
            else "atlas_social_yyyy_identity_acceptance_partial_or_blocked_report_only"
        ),
        "source_accepted_path": str(source_accepted_path),
        "rendered_evidence_path": str(rendered_evidence_path),
        "out_dir": str(out_dir),
        "report_path": str(report_path),
        "review_path": str(review_path),
        "accepted_path": str(accepted_path),
        "blocked_path": str(blocked_path),
        "source_rows": len(source_rows),
        "rendered_rows": len(rendered_rows),
        "identity_acceptance_passed": len(accepted_rows),
        "blocked_rows": len(blocked_rows),
        "accepted_entities": [row["name"] for row in accepted_rows],
        "decision_counts": dict(sorted(decision_counts.items())),
        "accepted_for_graph": 0,
        "identity_proof_promoted": 0,
        "avatar_display_allowed": 0,
        "public_serving_field_allowed": 0,
        "graph_write_allowed": 0,
        "next_gate": "Separate graph/write gate is still required before product truth, public serving, Neo4j, Qdrant, SQLite, avatar display, public fields, deploy, or memory writes.",
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
            "mem0_or_agentmemory_write_executed": False,
            "secret_value_read_or_printed": False,
            "d_scan_executed": False,
        },
    }
    write_json(summary_path, summary)
    write_markdown(out_dir / "atlas_social_yyyy_identity_acceptance_summary.md", summary, review_rows)
    write_markdown(report_path, summary, review_rows, top_level=True)
    return summary


def write_markdown(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]], top_level: bool = False) -> None:
    title = "Atlas T6 YYYY Identity Acceptance Gate" if top_level else "Atlas Social YYYY Identity Acceptance"
    lines = [
        f"# {title}",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- source_rows: `{summary['source_rows']}`",
        f"- rendered_rows: `{summary['rendered_rows']}`",
        f"- identity_acceptance_passed: `{summary['identity_acceptance_passed']}`",
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
    lines.extend(f"- `{entity}`" for entity in summary["accepted_entities"]) if summary["accepted_entities"] else lines.append("- none")
    lines.extend(["", "## Review Rows", ""])
    for row in rows:
        lines.append(
            "- `{name}` `{entity}`: decision `{decision}`, events `{events}`, source_articles `{articles}`, target `{target}`".format(
                name=row["name"],
                entity=row["entity_search_id"],
                decision=row["identity_acceptance_decision"],
                events=row["exact_event_count"],
                articles=row["exact_source_article_count"],
                target=row["target_url"],
            )
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only gate; no network/model/API call was executed by this script.",
            "- No product truth, identity proof promotion, avatar display, public serving field, graph/vector/DB write, deploy, or memory write was enabled.",
            "- Accepted rows are staging-review identity candidates only and still require a separate graph/write gate.",
            "",
            "## Next Gate",
            "",
            summary["next_gate"],
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-accepted", type=Path, default=DEFAULT_SOURCE_ACCEPTED)
    parser.add_argument("--rendered-evidence", type=Path, default=DEFAULT_RENDERED_EVIDENCE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_gate(
        source_accepted_path=args.source_accepted,
        rendered_evidence_path=args.rendered_evidence,
        out_dir=args.out_dir,
        report_path=args.report,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
