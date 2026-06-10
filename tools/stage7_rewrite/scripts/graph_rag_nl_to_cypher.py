"""Rule-based NL to read-only Cypher canary for PRD-19 Graph RAG.

This is a deterministic staging canary, not an LLM translator. It creates
auditable read-only Cypher plans against `Stage7Staging` labels and writes
reports only.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


DEFAULT_QUERIES = Path("queries/graph_rag_test_queries.jsonl")
DEFAULT_OUT_DIR = Path("reports/graph_rag_nl2cypher_20260515")
DEFAULT_RUN_ID = "stage7_qwen3_20260514"
DEFAULT_PROMOTION_RUN_ID = "stage7_production_graph_20260515"
WRITE_KEYWORDS = {
    "CREATE",
    "MERGE",
    "SET",
    "DELETE",
    "DETACH",
    "REMOVE",
    "DROP",
    "CALL DBMS",
    "LOAD CSV",
}
KNOWN_TERMS = [
    ("hybrid beats", "hybrid beats"),
    ("raw meat", "raw meat"),
    ("hakka bar", "hakka bar"),
    ("heim", "heim"),
    ("dada", "dada"),
    ("oil", "oil"),
    ("fat-k", "fat-k"),
    ("chica", "chica"),
    ("yangyang", "yangyang"),
    ("jaya", "jaya"),
    ("院吧", "hakka bar"),
    ("生肉", "raw meat"),
]
ENTITY_TERMS = {"oil", "fat-k", "chica", "yangyang", "jaya"}
EVENT_TERMS = {"dada", "heim", "hakka bar", "hybrid beats", "raw meat"}


EVENT_SEARCH_CYPHER = """
MATCH (a:Stage7Staging:Article {run_id: $run_id})-[r:STAGE7_EDGE {run_id: $run_id, predicate: 'ARTICLE_REPORTS_EVENT'}]->(ev:Stage7Staging:Event {run_id: $run_id})
WHERE toLower(coalesce(ev.name, '')) CONTAINS toLower($term)
   OR toLower(coalesce(ev.place_text, '')) CONTAINS toLower($term)
   OR toLower(coalesce(a.title, '')) CONTAINS toLower($term)
RETURN a.article_uid AS source_article_uid,
       a.title AS article_title,
       ev.node_id AS event_node_id,
       ev.name AS event_name,
       ev.time_text AS time_text,
       ev.place_text AS place,
       ev.participants_json AS participants_json
LIMIT 10
""".strip()


ENTITY_SEARCH_CYPHER = """
MATCH (a:Stage7Staging:Article {run_id: $run_id})-[r:STAGE7_EDGE {run_id: $run_id, predicate: 'ARTICLE_MENTIONS_ENTITY'}]->(e:Stage7Staging:Entity {run_id: $run_id})
WHERE toLower(coalesce(e.name, '')) CONTAINS toLower($term)
   OR toLower(coalesce(e.aliases_json, '')) CONTAINS toLower($term)
   OR toLower(coalesce(a.title, '')) CONTAINS toLower($term)
RETURN a.article_uid AS source_article_uid,
       a.title AS article_title,
       e.node_id AS entity_node_id,
       e.name AS entity_name,
       e.entity_type AS entity_type,
       e.bio AS bio,
       e.confidence AS confidence
LIMIT 10
""".strip()


EVENT_SEARCH_PRODUCTION_CYPHER = """
MATCH (a:Article {run_id: $run_id, promotion_run_id: $promotion_run_id})-[r:STAGE7_EDGE {run_id: $run_id, predicate: 'ARTICLE_REPORTS_EVENT'}]->(ev:Event {run_id: $run_id, promotion_run_id: $promotion_run_id})
WHERE toLower(coalesce(ev.name, '')) CONTAINS toLower($term)
   OR toLower(coalesce(ev.place_text, '')) CONTAINS toLower($term)
   OR toLower(coalesce(a.title, '')) CONTAINS toLower($term)
RETURN a.article_uid AS source_article_uid,
       a.title AS article_title,
       ev.node_id AS event_node_id,
       ev.name AS event_name,
       ev.time_text AS time_text,
       ev.place_text AS place,
       ev.participants_json AS participants_json
LIMIT 10
""".strip()


ENTITY_SEARCH_PRODUCTION_CYPHER = """
MATCH (a:Article {run_id: $run_id, promotion_run_id: $promotion_run_id})-[r:STAGE7_EDGE {run_id: $run_id, predicate: 'ARTICLE_MENTIONS_ENTITY'}]->(e:Entity {run_id: $run_id, promotion_run_id: $promotion_run_id})
WHERE toLower(coalesce(e.name, '')) CONTAINS toLower($term)
   OR toLower(coalesce(e.aliases_json, '')) CONTAINS toLower($term)
   OR toLower(coalesce(a.title, '')) CONTAINS toLower($term)
RETURN a.article_uid AS source_article_uid,
       a.title AS article_title,
       e.node_id AS entity_node_id,
       e.name AS entity_name,
       e.entity_type AS entity_type,
       e.bio AS bio,
       e.confidence AS confidence
LIMIT 10
""".strip()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def iter_jsonl(path: Path, limit: int = 0) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle, start=1):
            if limit and idx > limit:
                break
            line = line.strip()
            if line:
                yield json.loads(line)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
    tmp.replace(path)


def infer_term(query: str) -> str:
    lower = query.casefold()
    for needle, term in KNOWN_TERMS:
        if needle in lower:
            return term
    tokens = [token.strip(" ?？,，。") for token in query.split() if token.strip(" ?？,，。")]
    return tokens[0].casefold() if tokens else ""


def infer_intent(query: str) -> str:
    term = infer_term(query)
    if term in ENTITY_TERMS:
        return "entity_search"
    if term in EVENT_TERMS:
        return "event_search"
    lower = query.casefold()
    if any(word in lower for word in ("活动", "演出", "场地", "event", "where", "lineup")):
        return "event_search"
    return "entity_search"


def is_read_only_cypher(cypher: str) -> bool:
    upper = " ".join(cypher.upper().split())
    return upper.startswith("MATCH ") and not any(keyword in upper for keyword in WRITE_KEYWORDS)


def plan_query(
    row: dict[str, Any],
    run_id: str,
    *,
    use_production_labels: bool = False,
    promotion_run_id: str = DEFAULT_PROMOTION_RUN_ID,
) -> dict[str, Any]:
    query = str(row.get("query") or "")
    intent = infer_intent(query)
    term = infer_term(query)
    if use_production_labels:
        cypher = EVENT_SEARCH_PRODUCTION_CYPHER if intent == "event_search" else ENTITY_SEARCH_PRODUCTION_CYPHER
        parameters = {"run_id": run_id, "promotion_run_id": promotion_run_id, "term": term}
        label_mode = "production"
    else:
        cypher = EVENT_SEARCH_CYPHER if intent == "event_search" else ENTITY_SEARCH_CYPHER
        parameters = {"run_id": run_id, "term": term}
        label_mode = "staging"
    read_only = is_read_only_cypher(cypher)
    return {
        "id": row.get("id") or "",
        "query": query,
        "intent": intent,
        "term": term,
        "cypher": cypher,
        "parameters": parameters,
        "label_mode": label_mode,
        "read_only": read_only,
        "expected_intent": row.get("expected_intent", ""),
        "expected_term": row.get("expected_term", ""),
        "intent_matches_expected": not row.get("expected_intent") or intent == row.get("expected_intent"),
        "term_matches_expected": not row.get("expected_term") or term == row.get("expected_term"),
    }


def build_plans(
    rows: Iterable[dict[str, Any]],
    run_id: str,
    *,
    use_production_labels: bool = False,
    promotion_run_id: str = DEFAULT_PROMOTION_RUN_ID,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    plans = [
        plan_query(
            row,
            run_id,
            use_production_labels=use_production_labels,
            promotion_run_id=promotion_run_id,
        )
        for row in rows
    ]
    summary = {
        "schema_version": "stage7_graph_rag_nl2cypher.v1",
        "generated_at": now_iso(),
        "run_id": run_id,
        "label_mode": "production" if use_production_labels else "staging",
        "promotion_run_id": promotion_run_id if use_production_labels else "",
        "query_count": len(plans),
        "read_only_count": sum(1 for plan in plans if plan["read_only"]),
        "intent_match_count": sum(1 for plan in plans if plan["intent_matches_expected"]),
        "term_match_count": sum(1 for plan in plans if plan["term_matches_expected"]),
        "decision": "nl2cypher_canary_ready" if plans and all(plan["read_only"] for plan in plans) else "nl2cypher_canary_blocked",
        "safety": {
            "report_only": True,
            "llm_call_executed": False,
            "neo4j_write_executed": False,
            "production_write_executed": False,
        },
    }
    return plans, summary


def write_markdown(path: Path, summary: dict[str, Any], plans: list[dict[str, Any]]) -> None:
    lines = [
        "# Graph RAG NL to Cypher Canary",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- query_count: `{summary['query_count']}`",
        f"- read_only_count: `{summary['read_only_count']}`",
        "",
        "| ID | Intent | Term | Read Only |",
        "|---|---|---|---|",
    ]
    for plan in plans:
        lines.append(f"| `{plan['id']}` | `{plan['intent']}` | `{plan['term']}` | `{plan['read_only']}` |")
    lines.extend(["", "## Safety", "", "- Deterministic rule-based planner. No LLM call and no Neo4j write."])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    plans, summary = build_plans(
        iter_jsonl(args.queries, limit=args.limit),
        args.run_id,
        use_production_labels=args.use_production_labels,
        promotion_run_id=args.promotion_run_id,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.out_dir / "graph_rag_cypher_plans.jsonl", plans)
    write_json(args.out_dir / "graph_rag_nl2cypher_summary.json", summary)
    write_markdown(args.out_dir / "graph_rag_nl2cypher_summary.md", summary, plans)
    print(json.dumps({"ok": summary["decision"] == "nl2cypher_canary_ready", "query_count": len(plans), "summary": str(args.out_dir / "graph_rag_nl2cypher_summary.json")}, ensure_ascii=False, indent=2))
    return 0 if summary["decision"] == "nl2cypher_canary_ready" else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["canary"], default="canary")
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--use-production-labels", action="store_true")
    parser.add_argument("--promotion-run-id", default=DEFAULT_PROMOTION_RUN_ID)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
