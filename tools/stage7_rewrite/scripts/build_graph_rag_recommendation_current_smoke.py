#!/usr/bin/env python3
"""Build a current graph/RAG/recommendation smoke gate from latest reports.

This is a report-only synthesis gate. It consumes existing vector-router,
graph recommendation, hybrid recommendation, Graph RAG answer, and consumer
query smoke reports. It does not query Neo4j/Qdrant, run models, publish, or
write production state.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "stage7_graph_rag_recommendation_current_smoke.v1"
DEFAULT_OUT_DIR = Path("reports/graph_rag_recommendation_current_smoke_20260518")
DEFAULT_VECTOR_ROUTER = Path("reports/vector_collection_router_smoke_20260518/vector_collection_router_smoke.json")
DEFAULT_GRAPH_RECOMMEND = Path("reports/graph_recommend_canary_20260517/graph_recommend_canary.json")
DEFAULT_HYBRID_RECOMMEND = Path("reports/hybrid_recommend_canary_20260517/hybrid_recommend_canary.json")
DEFAULT_GRAPH_RAG_ANSWER = Path("reports/graph_rag_answer_20260517/graph_rag_answer_summary.json")
DEFAULT_CONSUMER_QUERY_SMOKE = Path("reports/consumer_query_smoke_production_labels_20260517/consumer_query_smoke.json")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_broad_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"} or raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses broad D root: {path}")


def read_json(path: Path) -> dict[str, Any]:
    reject_broad_d_path(path, "json")
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def norm_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def build_report(
    *,
    vector_router: dict[str, Any],
    graph_recommend: dict[str, Any],
    hybrid_recommend: dict[str, Any],
    graph_rag_answer: dict[str, Any],
    consumer_query_smoke: dict[str, Any],
    paths: dict[str, Path],
) -> dict[str, Any]:
    gates = {
        "vector_router_ready": bool(vector_router.get("ok"))
        and vector_router.get("decision") == "vector_collection_router_smoke_ready",
        "graph_recommend_ready": graph_recommend.get("decision") == "graph_recommendations_ready"
        and int(graph_recommend.get("recommendation_count") or 0) >= 10,
        "hybrid_recommend_ready": hybrid_recommend.get("decision") == "hybrid_recommendations_ready_without_mem0"
        and int(hybrid_recommend.get("recommendation_count") or 0) >= 10
        and bool(hybrid_recommend.get("diversity_gate_met")),
        "graph_rag_answers_ready": graph_rag_answer.get("decision") == "answer_drafts_ready_without_llm"
        and int(graph_rag_answer.get("answer_count") or 0) > 0
        and int(graph_rag_answer.get("answers_with_citations") or 0) == int(graph_rag_answer.get("answer_count") or 0),
        "consumer_query_smoke_ready": bool(consumer_query_smoke.get("ok"))
        and bool((consumer_query_smoke.get("qdrant") or {}).get("ok"))
        and bool((consumer_query_smoke.get("neo4j") or {}).get("ok")),
    }
    blockers = [name for name, ok in gates.items() if not ok]
    warnings = list(hybrid_recommend.get("blockers") or [])
    consumer_qdrant = consumer_query_smoke.get("qdrant") or {}
    consumer_current_alias_confirmed = bool(consumer_qdrant.get("ok")) and float(
        consumer_qdrant.get("equivalent_rate") or 0.0
    ) >= 1.0
    if (
        not bool(vector_router.get("safety", {}).get("qdrant_alias_change_executed"))
        and not consumer_current_alias_confirmed
    ):
        warnings.append("vector router smoke did not promote aliases; service must keep report-backed status until an explicit alias packet runs")
    if not bool(graph_rag_answer.get("safety", {}).get("llm_call_executed")):
        warnings.append("Graph RAG answers are deterministic drafts without LLM calls")
    decision = (
        "graph_rag_recommendation_current_smoke_ready_report_only"
        if not blockers
        else "graph_rag_recommendation_current_smoke_blocked"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": not blockers,
        "decision": decision,
        "report_only": True,
        "inputs": {key: norm_path(path) for key, path in paths.items()},
        "gates": gates,
        "blockers": blockers,
        "warnings": warnings,
        "summary": {
            "vector_router_decision": vector_router.get("decision"),
            "vector_router_cases": len(vector_router.get("router_cases") or []),
            "graph_recommendation_count": graph_recommend.get("recommendation_count"),
            "graph_edge_count": graph_recommend.get("edge_count"),
            "hybrid_recommendation_count": hybrid_recommend.get("recommendation_count"),
            "hybrid_type_counts": hybrid_recommend.get("type_counts"),
            "graph_rag_answer_count": graph_rag_answer.get("answer_count"),
            "graph_rag_answers_with_citations": graph_rag_answer.get("answers_with_citations"),
            "consumer_qdrant_equivalent_rate": (consumer_query_smoke.get("qdrant") or {}).get("equivalent_rate"),
            "consumer_neo4j_row_count": (consumer_query_smoke.get("neo4j") or {}).get("row_count"),
        },
        "allowed_next_actions": [
            "Use this as evidence for service-layer read paths and publish packets.",
            "Keep CloudRun search in materialized_text_scan until a separate live vector search packet is implemented.",
            "Run production publish/write/deploy only through packets that record each action separately.",
        ],
        "forbidden_next_actions": [
            "Do not claim live vector search is enabled from this report.",
            "Do not promote Qdrant aliases from this report.",
            "Do not write mem0 personalization from this report.",
            "Do not treat deterministic Graph RAG drafts as LLM-generated answers.",
        ],
        "safety": {
            "report_only": True,
            "model_call_executed": False,
            "qdrant_query_executed": False,
            "qdrant_write_executed": False,
            "qdrant_alias_change_executed": False,
            "neo4j_query_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "production_publish_executed": False,
            "d_scan_executed": False,
        },
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Graph/RAG/Recommendation Current Smoke",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- decision: `{report['decision']}`",
        "",
        "## Gates",
        "",
    ]
    for key, value in report["gates"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Summary", ""])
    for key, value in report["summary"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Warnings", ""])
    for item in report["warnings"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(report["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    paths = {
        "vector_router": args.vector_router,
        "graph_recommend": args.graph_recommend,
        "hybrid_recommend": args.hybrid_recommend,
        "graph_rag_answer": args.graph_rag_answer,
        "consumer_query_smoke": args.consumer_query_smoke,
    }
    report = build_report(
        vector_router=read_json(args.vector_router),
        graph_recommend=read_json(args.graph_recommend),
        hybrid_recommend=read_json(args.hybrid_recommend),
        graph_rag_answer=read_json(args.graph_rag_answer),
        consumer_query_smoke=read_json(args.consumer_query_smoke),
        paths=paths,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.out_dir / "graph_rag_recommendation_current_smoke.json"
    md_path = args.out_dir / "graph_rag_recommendation_current_smoke.md"
    write_json(report_path, report)
    write_markdown(md_path, report)
    print(json.dumps({"ok": report["ok"], "decision": report["decision"], "report": str(report_path)}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vector-router", type=Path, default=DEFAULT_VECTOR_ROUTER)
    parser.add_argument("--graph-recommend", type=Path, default=DEFAULT_GRAPH_RECOMMEND)
    parser.add_argument("--hybrid-recommend", type=Path, default=DEFAULT_HYBRID_RECOMMEND)
    parser.add_argument("--graph-rag-answer", type=Path, default=DEFAULT_GRAPH_RAG_ANSWER)
    parser.add_argument("--consumer-query-smoke", type=Path, default=DEFAULT_CONSUMER_QUERY_SMOKE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
