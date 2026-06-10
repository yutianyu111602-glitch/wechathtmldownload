#!/usr/bin/env python3
"""Validate PRD-07 graph promotion readiness without applying labels.

This report-only validator combines local Neo4j read-only counts with Stage7
evidence reports. It never runs SET/REMOVE/MERGE, never applies production
labels, and never changes consumer or graph state.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


DEFAULT_NEO4J_URI = "http://127.0.0.1:7474"
DEFAULT_RUN_ID = "stage7_qwen3_20260514"
DEFAULT_TYPED_RUN_ID = "stage7_qwen3_typed_20260514"
DEFAULT_PROMOTION_RUN_ID = "stage7_production_graph_20260515"
DEFAULT_P1_SOCIAL_RUN_ID = "stage7_p1_social_20260515"
DEFAULT_OUT_DIR = Path("reports/graph_promotion_readiness_20260515")

DEFAULT_STAGING_REPORT = Path("reports/neo4j_stage7_staging_20260514/neo4j_stage7_staging_report.json")
DEFAULT_TYPED_REPORT = Path("reports/neo4j_stage7_typed_edges_20260514/neo4j_stage7_typed_edge_promotion.json")
DEFAULT_P1_SOCIAL_VERIFY = Path("reports/neo4j_p1_social_staging_20260515/canary_verification.json")
DEFAULT_SOCIAL_DEEP = Path("reports/social_deep_edge_pack_20260515/social_deep_edge_pack_summary.json")
DEFAULT_OPENCLI_IDENTITY_REVIEW = Path(
    "reports/opencli_social_identity_review_20260516/opencli_identity_review_summary.json"
)
DEFAULT_STRICT_IDENTITY_ACCEPTANCE = Path(
    "reports/social_identity_strict_acceptance_review_20260517/social_identity_strict_acceptance_review.json"
)
DEFAULT_CDCR_REVIEW = Path("reports/p1_cdcr_direct_source_review_20260516/cdcr_direct_source_review_summary.json")
DEFAULT_CDCR_STRICT_ACCEPTANCE = Path(
    "reports/cdcr_strict_acceptance_review_20260517/cdcr_strict_acceptance_review.json"
)
DEFAULT_CANONICAL = Path("reports/canonical_entities_20260515/canonical_entities_summary.json")
DEFAULT_CANONICAL_FUZZY_REVIEW = Path(
    "reports/canonical_fuzzy_review_gate_packet_20260517/canonical_fuzzy_review_gate_packet.json"
)
DEFAULT_CONSUMER_GATE = Path("reports/consumer_publish_gate_review_20260515/consumer_publish_gate_review.json")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def read_live_counts_source(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    live_counts = payload.get("live_counts") if isinstance(payload.get("live_counts"), dict) else payload
    return dict(live_counts) if isinstance(live_counts, dict) else {}


def required_input_paths(args: argparse.Namespace) -> dict[str, Path]:
    return {
        "staging_report": args.staging_report,
        "typed_report": args.typed_report,
        "p1_social_verify": args.p1_social_verify,
        "social_deep_report": args.social_deep_report,
        "opencli_identity_review": args.opencli_identity_review,
        "strict_identity_acceptance": args.strict_identity_acceptance,
        "cdcr_review": args.cdcr_review,
        "cdcr_strict_acceptance": args.cdcr_strict_acceptance,
        "canonical_report": args.canonical_report,
        "canonical_fuzzy_review": args.canonical_fuzzy_review,
        "consumer_gate_report": args.consumer_gate_report,
    }


def find_missing_inputs(args: argparse.Namespace) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    for name, path in required_input_paths(args).items():
        if not path.exists():
            missing.append({"input": name, "path": str(path)})
    return missing


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def require_local_neo4j(uri: str) -> None:
    parsed = urlparse(uri)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"Neo4j URI must be local for graph promotion readiness checks: {uri}")


def neo4j_commit(neo4j_uri: str, database: str, statements: list[dict[str, Any]]) -> dict[str, Any]:
    response = requests.post(
        f"{neo4j_uri.rstrip('/')}/db/{database}/tx/commit",
        json={"statements": statements},
        timeout=60,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Neo4j read failed {response.status_code}: {response.text[:500]}")
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(f"Neo4j returned errors: {json.dumps(payload['errors'][:3], ensure_ascii=False)}")
    return payload


def scalar_results(payload: dict[str, Any]) -> list[int]:
    values: list[int] = []
    for result in payload.get("results") or []:
        data = result.get("data") or []
        if not data:
            values.append(0)
            continue
        row = data[0].get("row") or [0]
        values.append(int(row[0] or 0))
    return values


def live_read_counts(
    neo4j_uri: str,
    database: str,
    run_id: str,
    typed_run_id: str,
    promotion_run_id: str,
    p1_social_run_id: str,
) -> dict[str, Any]:
    require_local_neo4j(neo4j_uri)
    statements = [
        {
            "statement": "MATCH (n:Stage7Staging:Article {run_id:$run_id}) RETURN count(n)",
            "parameters": {"run_id": run_id},
        },
        {
            "statement": "MATCH (n:Stage7Staging:Entity {run_id:$run_id}) RETURN count(n)",
            "parameters": {"run_id": run_id},
        },
        {
            "statement": "MATCH (n:Stage7Staging:Event {run_id:$run_id}) RETURN count(n)",
            "parameters": {"run_id": run_id},
        },
        {
            "statement": "MATCH (n:Article {run_id:$run_id}) RETURN count(n)",
            "parameters": {"run_id": run_id},
        },
        {
            "statement": "MATCH (n:Entity {run_id:$run_id}) RETURN count(n)",
            "parameters": {"run_id": run_id},
        },
        {
            "statement": "MATCH (n:Event {run_id:$run_id}) RETURN count(n)",
            "parameters": {"run_id": run_id},
        },
        {
            "statement": "MATCH (n:Article {promotion_run_id:$promotion_run_id}) RETURN count(n)",
            "parameters": {"promotion_run_id": promotion_run_id},
        },
        {
            "statement": "MATCH (n:Entity {promotion_run_id:$promotion_run_id}) RETURN count(n)",
            "parameters": {"promotion_run_id": promotion_run_id},
        },
        {
            "statement": "MATCH (n:Event {promotion_run_id:$promotion_run_id}) RETURN count(n)",
            "parameters": {"promotion_run_id": promotion_run_id},
        },
        {
            "statement": "MATCH ()-[r:MENTIONS {typed_run_id:$typed_run_id}]->() RETURN count(r)",
            "parameters": {"typed_run_id": typed_run_id},
        },
        {
            "statement": "MATCH ()-[r:REPORTS {typed_run_id:$typed_run_id}]->() RETURN count(r)",
            "parameters": {"typed_run_id": typed_run_id},
        },
        {
            "statement": "MATCH (:Stage7Staging)-[r:HAS_PROFILE {run_id:$p1_social_run_id}]->(:Stage7Staging) RETURN count(r)",
            "parameters": {"p1_social_run_id": p1_social_run_id},
        },
    ]
    values = scalar_results(neo4j_commit(neo4j_uri, database, statements))
    keys = [
        "staging_article",
        "staging_entity",
        "staging_event",
        "label_article_with_run_id",
        "label_entity_with_run_id",
        "label_event_with_run_id",
        "promoted_article_by_promotion_run_id",
        "promoted_entity_by_promotion_run_id",
        "promoted_event_by_promotion_run_id",
        "typed_mentions",
        "typed_reports",
        "staging_has_profile",
    ]
    return dict(zip(keys, values, strict=True))


def count_by_key(rows: list[dict[str, Any]], name_key: str, count_key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        if isinstance(row, dict) and row.get(name_key):
            result[str(row[name_key])] = int(row.get(count_key) or 0)
    return result


def build_decision(
    *,
    staging_report: dict[str, Any],
    typed_report: dict[str, Any],
    p1_social_verify: dict[str, Any],
    social_deep: dict[str, Any],
    opencli_identity_review: dict[str, Any] | None = None,
    strict_identity_acceptance: dict[str, Any] | None = None,
    cdcr_review: dict[str, Any] | None = None,
    cdcr_strict_acceptance: dict[str, Any] | None = None,
    canonical: dict[str, Any],
    canonical_fuzzy_review: dict[str, Any] | None = None,
    consumer_gate: dict[str, Any],
    live_counts: dict[str, Any],
    run_id: str,
    typed_run_id: str,
    promotion_run_id: str,
    p1_social_run_id: str = DEFAULT_P1_SOCIAL_RUN_ID,
) -> dict[str, Any]:
    opencli_identity_review = opencli_identity_review or {}
    strict_identity_acceptance = strict_identity_acceptance or {}
    cdcr_review = cdcr_review or {}
    cdcr_strict_acceptance = cdcr_strict_acceptance or {}
    canonical_fuzzy_review = canonical_fuzzy_review or {}
    staging_state = staging_report.get("state") or {}
    staging_complete = bool(staging_state.get("complete")) and int(live_counts.get("staging_article") or 0) > 0
    expected_nodes = staging_report.get("node_counter_this_run") or {}
    expected_edges = staging_report.get("edge_counter_this_run") or {}
    typed_counts = count_by_key(typed_report.get("after_typed_counts") or [], "type", "count")
    typed_edges_ready = (
        typed_counts.get("MENTIONS", 0) == int(expected_edges.get("ARTICLE_MENTIONS_ENTITY") or 0)
        and typed_counts.get("REPORTS", 0) == int(expected_edges.get("ARTICLE_REPORTS_EVENT") or 0)
    )
    live_staging_counts_present = (
        int(live_counts.get("staging_article") or 0) == int(expected_nodes.get("article") or 0)
        and int(live_counts.get("staging_entity") or 0) > 0
        and int(live_counts.get("staging_event") or 0) > 0
    )
    production_labels_with_promotion_id = {
        "article": int(live_counts.get("promoted_article_by_promotion_run_id") or 0),
        "entity": int(live_counts.get("promoted_entity_by_promotion_run_id") or 0),
        "event": int(live_counts.get("promoted_event_by_promotion_run_id") or 0),
    }

    no_current_promotion = all(count == 0 for count in production_labels_with_promotion_id.values())
    p1_social_ready = bool(p1_social_verify.get("ok")) and int((p1_social_verify.get("counts") or {}).get("has_profile_edges") or 0) >= 2
    strict_accepted_edges = int(strict_identity_acceptance.get("accepted_edges") or 0)
    strict_cdcr_overlap = int(strict_identity_acceptance.get("cdcr_subject_overlap_accepted_count") or 0)
    social_deep_review_blocked = (
        int(social_deep.get("accepted_edges") or 0) + strict_accepted_edges == 0
        and int(social_deep.get("candidate_edges") or 0) > 0
    )
    opencli_review_ready = opencli_identity_review.get("decision") == "opencli_identity_review_ready"
    opencli_identity_review_blocked = (
        opencli_review_ready
        and int(opencli_identity_review.get("accepted_edges") or 0) + strict_accepted_edges == 0
        and int(opencli_identity_review.get("strong_opencli_review_candidates") or 0) > 0
    )
    cdcr_review_ready = cdcr_review.get("decision") == "cdcr_direct_source_review_ready"
    cdcr_strict_accepted = int(cdcr_strict_acceptance.get("accepted_edges") or 0)
    cdcr_review_blocked = (
        cdcr_review_ready
        and int(cdcr_review.get("accepted_edges") or 0) + strict_cdcr_overlap + cdcr_strict_accepted == 0
        and int(cdcr_review.get("graph_ready_rows") or 0) + strict_cdcr_overlap + cdcr_strict_accepted == 0
        and int(cdcr_review.get("direct_source_candidates") or 0) > 0
    )
    canonical_ready = bool(canonical.get("ok")) and int(canonical.get("canonical_exact_groups") or 0) >= 100
    canonical_fuzzy_review_gate_ready = (
        canonical_fuzzy_review.get("decision") == "canonical_fuzzy_review_gate_ready_report_only"
        and bool(canonical_fuzzy_review.get("future_fuzzy_merge_write_deferred"))
        and int(canonical_fuzzy_review.get("unreviewed_candidates") or 0) == 0
    )
    canonical_review_needed = int(canonical.get("fuzzy_review_candidates") or 0) > 0 and not canonical_fuzzy_review_gate_ready
    consumer_publish_allowed = bool(consumer_gate.get("publish_allowed"))
    production_policy_allows = bool(consumer_gate.get("production_graph_labels_allowed"))

    blockers = []
    if not production_policy_allows:
        blockers.append("production graph labels are globally forbidden")
    if not consumer_publish_allowed:
        blockers.append("consumer production publish gate is blocked")
    if social_deep_review_blocked:
        blockers.append("PRD-16 social-deep candidates have 0 accepted edges")
    if opencli_identity_review_blocked:
        blockers.append("PRD-16 OpenCLI identity review has 0 accepted edges")
    if cdcr_review_blocked:
        blockers.append("PRD-02 CDCR review has 0 graph-ready accepted edges")
    if canonical_review_needed:
        blockers.append("PRD-14 fuzzy canonical candidates require review before future merge/write")
    if not staging_complete:
        blockers.append("staging graph is not complete")
    if not typed_edges_ready:
        blockers.append("typed staging edge counts do not match generic edge counts")
    if not live_staging_counts_present:
        blockers.append("live staging node counts are missing or article count does not match report")

    promotion_allowed = (
        production_policy_allows
        and consumer_publish_allowed
        and staging_complete
        and typed_edges_ready
        and live_staging_counts_present
        and p1_social_ready
        and canonical_ready
        and not social_deep_review_blocked
        and not opencli_identity_review_blocked
        and not cdcr_review_blocked
    )
    decision = "graph_promotion_ready" if promotion_allowed else "graph_promotion_blocked_report_ready"
    return {
        "schema_version": "stage7_graph_promotion_readiness.v1",
        "generated_at": now_iso(),
        "ok": True,
        "decision": decision,
        "promotion_allowed": promotion_allowed,
        "report_only": True,
        "run_id": run_id,
        "typed_run_id": typed_run_id,
        "promotion_run_id": promotion_run_id,
        "p1_social_run_id": p1_social_run_id,
        "blockers": blockers,
        "gates": {
            "staging_complete": staging_complete,
            "typed_edges_ready": typed_edges_ready,
            "live_staging_counts_present": live_staging_counts_present,
            "p1_social_ready": p1_social_ready,
            "social_deep_review_blocked": social_deep_review_blocked,
            "opencli_identity_review_blocked": opencli_identity_review_blocked,
            "cdcr_review_blocked": cdcr_review_blocked,
            "canonical_ready": canonical_ready,
            "canonical_fuzzy_review_gate_ready": canonical_fuzzy_review_gate_ready,
            "canonical_review_needed": canonical_review_needed,
            "consumer_publish_allowed": consumer_publish_allowed,
            "production_policy_allows": production_policy_allows,
            "no_current_promotion_for_promotion_run_id": no_current_promotion,
        },
        "expected_counts": {
            "submitted_staging_node_rows_by_type": expected_nodes,
            "generic_edges_by_predicate": expected_edges,
            "typed_edges_by_type": typed_counts,
        },
        "live_counts": live_counts,
        "review_inputs": {
            "social_deep": {
                "candidate_edges": social_deep.get("candidate_edges"),
                "accepted_edges": social_deep.get("accepted_edges"),
            },
            "opencli_identity_review": {
                "decision": opencli_identity_review.get("decision"),
                "accepted_edges": opencli_identity_review.get("accepted_edges"),
                "strong_opencli_review_candidates": opencli_identity_review.get("strong_opencli_review_candidates"),
                "medium_opencli_review_candidates": opencli_identity_review.get("medium_opencli_review_candidates"),
            },
            "strict_identity_acceptance": {
                "decision": strict_identity_acceptance.get("decision"),
                "accepted_edges": strict_identity_acceptance.get("accepted_edges"),
                "accepted_subjects": strict_identity_acceptance.get("accepted_subjects"),
                "cdcr_subject_overlap_accepted_count": strict_identity_acceptance.get(
                    "cdcr_subject_overlap_accepted_count"
                ),
            },
            "cdcr_review": {
                "decision": cdcr_review.get("decision"),
                "accepted_edges": cdcr_review.get("accepted_edges"),
                "graph_ready_rows": cdcr_review.get("graph_ready_rows"),
                "direct_source_candidates": cdcr_review.get("direct_source_candidates"),
                "source_backed_profile_review_candidates": cdcr_review.get("source_backed_profile_review_candidates"),
            },
            "cdcr_strict_acceptance": {
                "decision": cdcr_strict_acceptance.get("decision"),
                "accepted_edges": cdcr_strict_acceptance.get("accepted_edges"),
                "accepted_subjects": cdcr_strict_acceptance.get("accepted_subjects"),
            },
            "canonical_fuzzy_review": {
                "decision": canonical_fuzzy_review.get("decision"),
                "reviewed_candidates": canonical_fuzzy_review.get("reviewed_candidates"),
                "unreviewed_candidates": canonical_fuzzy_review.get("unreviewed_candidates"),
                "accepted_merges": canonical_fuzzy_review.get("accepted_merges"),
                "deferred_merges": canonical_fuzzy_review.get("deferred_merges"),
                "future_fuzzy_merge_write_deferred": canonical_fuzzy_review.get("future_fuzzy_merge_write_deferred"),
            },
        },
        "notes": [
            "Staging report entity/event node counters are submitted rows; live Neo4j entity/event counts are unique MERGE results, so the validator treats live non-zero counts plus article-count equality as staging presence evidence.",
            "Counts for labels Article/Entity/Event with run_id may be non-zero because current staging nodes already carry type labels; promotion readiness is keyed by promotion_run_id and policy gates.",
            "This validator intentionally reports blockers instead of using a confirm token or applying production labels.",
        ],
        "required_before_real_promotion": [
            "Lift production graph label ban in the current authority layer.",
            "Define rollback owner and blue-green consumer switch gate.",
            "Pass consumer production publish/deploy gate.",
            "Resolve or explicitly defer PRD-16 social-deep identity review candidates.",
            "Resolve or explicitly defer PRD-02 CDCR graph-ready edge candidates.",
            "Review PRD-14 fuzzy canonical candidates before any automatic merge/write.",
            "Run a separate dry-run/verify cycle before any SET/REMOVE labels.",
        ],
        "safety": {
            "neo4j_write_executed": False,
            "production_label_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
            "publish_executed": False,
        },
        "writes": "reports_only",
    }


def build_missing_inputs_report(
    *,
    missing_inputs: list[dict[str, str]],
    live_counts: dict[str, Any],
    run_id: str,
    typed_run_id: str,
    promotion_run_id: str,
    p1_social_run_id: str = DEFAULT_P1_SOCIAL_RUN_ID,
) -> dict[str, Any]:
    return {
        "schema_version": "stage7_graph_promotion_readiness.v1",
        "generated_at": now_iso(),
        "ok": False,
        "decision": "graph_promotion_blocked_missing_inputs",
        "promotion_allowed": False,
        "report_only": True,
        "run_id": run_id,
        "typed_run_id": typed_run_id,
        "promotion_run_id": promotion_run_id,
        "p1_social_run_id": p1_social_run_id,
        "missing_inputs": missing_inputs,
        "blockers": [
            f"missing input report: {item['input']} -> {item['path']}" for item in missing_inputs
        ],
        "gates": {
            "inputs_present": False,
            "staging_complete": False,
            "typed_edges_ready": False,
            "live_staging_counts_present": False,
            "p1_social_ready": False,
            "social_deep_review_blocked": False,
            "opencli_identity_review_blocked": False,
            "cdcr_review_blocked": False,
            "canonical_ready": False,
            "canonical_fuzzy_review_gate_ready": False,
            "canonical_review_needed": False,
            "consumer_publish_allowed": False,
            "production_policy_allows": False,
            "no_current_promotion_for_promotion_run_id": True,
        },
        "expected_counts": {},
        "live_counts": live_counts,
        "review_inputs": {},
        "notes": [
            "The validator could not read one or more required evidence reports.",
            "This is a report-only blocker, not a Python crash and not a production promotion attempt.",
            "Pass explicit current evidence report paths or regenerate the missing reports before any real promotion review.",
        ],
        "required_before_real_promotion": [
            "Provide all required current evidence reports.",
            "Resolve every blocker emitted by this validator.",
            "Run a separate dry-run/verify cycle before any SET/REMOVE labels.",
        ],
        "safety": {
            "neo4j_write_executed": False,
            "production_label_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
            "publish_executed": False,
        },
        "writes": "reports_only",
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Graph Promotion Readiness",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- decision: `{report['decision']}`",
        f"- promotion_allowed: `{report['promotion_allowed']}`",
        f"- run_id: `{report['run_id']}`",
        f"- promotion_run_id: `{report['promotion_run_id']}`",
        "",
        "## Gates",
        "",
    ]
    for key, value in report["gates"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Blockers", ""])
    if report["blockers"]:
        for blocker in report["blockers"]:
            lines.append(f"- {blocker}")
    else:
        lines.append("- none")
    lines.extend(["", "## Live Counts", ""])
    for key, value in report["live_counts"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Required Before Real Promotion", ""])
    for item in report["required_before_real_promotion"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only.",
            "- Read-only Neo4j count queries only.",
            "- No production labels, graph writes, Qdrant writes, mem0 writes, paid APIs, D: scan, publish, or deploy.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    if args.live_counts_source:
        live_counts = read_live_counts_source(args.live_counts_source)
        if args.p1_social_verify.exists():
            p1_social_verify_for_counts = read_json(args.p1_social_verify)
            p1_counts = p1_social_verify_for_counts.get("counts") or {}
            live_counts["staging_has_profile"] = int(p1_counts.get("has_profile_edges") or 0)
            live_counts["staging_has_profile_run_id"] = args.p1_social_run_id
            live_counts["live_counts_source"] = str(args.live_counts_source)
    elif args.skip_live_neo4j:
        live_counts = {}
    else:
        live_counts = live_read_counts(
            args.neo4j_uri,
            args.neo4j_database,
            args.run_id,
            args.typed_run_id,
            args.promotion_run_id,
            args.p1_social_run_id,
        )
    missing_inputs = find_missing_inputs(args)
    if missing_inputs:
        report = build_missing_inputs_report(
            missing_inputs=missing_inputs,
            live_counts=live_counts,
            run_id=args.run_id,
            typed_run_id=args.typed_run_id,
            promotion_run_id=args.promotion_run_id,
            p1_social_run_id=args.p1_social_run_id,
        )
    else:
        report = build_decision(
            staging_report=read_json(args.staging_report),
            typed_report=read_json(args.typed_report),
            p1_social_verify=read_json(args.p1_social_verify),
            social_deep=read_json(args.social_deep_report),
            opencli_identity_review=read_json(args.opencli_identity_review),
            strict_identity_acceptance=read_json(args.strict_identity_acceptance),
            cdcr_review=read_json(args.cdcr_review),
            cdcr_strict_acceptance=read_json(args.cdcr_strict_acceptance),
            canonical=read_json(args.canonical_report),
            canonical_fuzzy_review=read_json(args.canonical_fuzzy_review),
            consumer_gate=read_json(args.consumer_gate_report),
            live_counts=live_counts,
            run_id=args.run_id,
            typed_run_id=args.typed_run_id,
            promotion_run_id=args.promotion_run_id,
            p1_social_run_id=args.p1_social_run_id,
        )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "graph_promotion_readiness.json", report)
    write_markdown(args.out_dir / "graph_promotion_readiness.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "promotion_allowed": report["promotion_allowed"],
                "blockers": report["blockers"],
                "report": str(args.out_dir / "graph_promotion_readiness.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] or args.report_only_exit_zero else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--neo4j-uri", default=DEFAULT_NEO4J_URI)
    parser.add_argument("--neo4j-database", default="neo4j")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--typed-run-id", default=DEFAULT_TYPED_RUN_ID)
    parser.add_argument("--promotion-run-id", default=DEFAULT_PROMOTION_RUN_ID)
    parser.add_argument("--p1-social-run-id", default=DEFAULT_P1_SOCIAL_RUN_ID)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--staging-report", type=Path, default=DEFAULT_STAGING_REPORT)
    parser.add_argument("--typed-report", type=Path, default=DEFAULT_TYPED_REPORT)
    parser.add_argument("--p1-social-verify", type=Path, default=DEFAULT_P1_SOCIAL_VERIFY)
    parser.add_argument("--social-deep-report", type=Path, default=DEFAULT_SOCIAL_DEEP)
    parser.add_argument("--opencli-identity-review", type=Path, default=DEFAULT_OPENCLI_IDENTITY_REVIEW)
    parser.add_argument("--strict-identity-acceptance", type=Path, default=DEFAULT_STRICT_IDENTITY_ACCEPTANCE)
    parser.add_argument("--cdcr-review", type=Path, default=DEFAULT_CDCR_REVIEW)
    parser.add_argument("--cdcr-strict-acceptance", type=Path, default=DEFAULT_CDCR_STRICT_ACCEPTANCE)
    parser.add_argument("--canonical-report", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--canonical-fuzzy-review", type=Path, default=DEFAULT_CANONICAL_FUZZY_REVIEW)
    parser.add_argument("--consumer-gate-report", type=Path, default=DEFAULT_CONSUMER_GATE)
    parser.add_argument("--live-counts-source", type=Path)
    parser.add_argument("--skip-live-neo4j", action="store_true")
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
