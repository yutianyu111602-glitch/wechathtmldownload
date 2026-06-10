"""Execute read-only Graph RAG Cypher plans against local Neo4j staging."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import requests


DEFAULT_PLANS = Path("reports/graph_rag_nl2cypher_20260515/graph_rag_cypher_plans.jsonl")
DEFAULT_OUT_DIR = Path("reports/graph_rag_retrieve_20260515")
DEFAULT_NEO4J_URI = "http://127.0.0.1:7474"
WRITE_KEYWORDS = {"CREATE", "MERGE", "SET", "DELETE", "DETACH", "REMOVE", "DROP", "LOAD CSV"}


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


def require_local_neo4j(uri: str) -> None:
    parsed = urlparse(uri)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"Neo4j URI must be local for Graph RAG retrieval: {uri}")


def is_read_only_cypher(cypher: str) -> bool:
    upper = " ".join(cypher.upper().split())
    return upper.startswith("MATCH ") and not any(keyword in upper for keyword in WRITE_KEYWORDS)


def neo4j_commit(neo4j_uri: str, database: str, statement: str, parameters: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(
        f"{neo4j_uri.rstrip('/')}/db/{database}/tx/commit",
        json={"statements": [{"statement": statement, "parameters": parameters}]},
        timeout=60,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Neo4j commit failed {response.status_code}: {response.text[:500]}")
    data = response.json()
    if data.get("errors"):
        raise RuntimeError(f"Neo4j returned errors: {json.dumps(data['errors'][:3], ensure_ascii=False)}")
    return data


def result_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    results = data.get("results") or []
    if not results:
        return []
    columns = results[0].get("columns") or []
    rows = []
    for item in results[0].get("data") or []:
        values = item.get("row") or []
        rows.append({str(column): values[idx] if idx < len(values) else None for idx, column in enumerate(columns)})
    return rows


def execute_plan(neo4j_uri: str, database: str, plan: dict[str, Any]) -> dict[str, Any]:
    cypher = str(plan.get("cypher") or "")
    if not plan.get("read_only") or not is_read_only_cypher(cypher):
        return {"id": plan.get("id"), "query": plan.get("query"), "status": "blocked_not_read_only", "rows": [], "citation_count": 0}
    data = neo4j_commit(neo4j_uri, database, cypher, plan.get("parameters") or {})
    rows = result_rows(data)
    citation_count = sum(1 for row in rows if row.get("source_article_uid"))
    return {
        "id": plan.get("id"),
        "query": plan.get("query"),
        "intent": plan.get("intent"),
        "term": plan.get("term"),
        "status": "ok",
        "row_count": len(rows),
        "citation_count": citation_count,
        "rows": rows,
    }


def build_summary(contexts: list[dict[str, Any]], neo4j_uri: str) -> dict[str, Any]:
    query_count = len(contexts)
    rows_total = sum(int(item.get("row_count") or 0) for item in contexts)
    citation_total = sum(int(item.get("citation_count") or 0) for item in contexts)
    return {
        "schema_version": "stage7_graph_rag_retrieve.v1",
        "generated_at": now_iso(),
        "neo4j_uri": neo4j_uri,
        "query_count": query_count,
        "contexts_with_rows": sum(1 for item in contexts if int(item.get("row_count") or 0) > 0),
        "rows_total": rows_total,
        "citation_total": citation_total,
        "decision": "graph_rag_context_ready" if rows_total > 0 and citation_total > 0 else "graph_rag_context_empty",
        "safety": {
            "report_only": True,
            "neo4j_write_executed": False,
            "llm_call_executed": False,
            "production_write_executed": False,
        },
    }


def write_markdown(path: Path, summary: dict[str, Any], contexts: list[dict[str, Any]]) -> None:
    lines = [
        "# Graph RAG Retrieval Canary",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- query_count: `{summary['query_count']}`",
        f"- contexts_with_rows: `{summary['contexts_with_rows']}`",
        f"- rows_total: `{summary['rows_total']}`",
        f"- citation_total: `{summary['citation_total']}`",
        "",
        "| ID | Intent | Term | Rows | Citations |",
        "|---|---|---|---:|---:|",
    ]
    for item in contexts:
        lines.append(f"| `{item.get('id')}` | `{item.get('intent')}` | `{item.get('term')}` | {item.get('row_count', 0)} | {item.get('citation_count', 0)} |")
    lines.extend(["", "## Safety", "", "- Read-only Neo4j staging query. No LLM call and no graph write."])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    require_local_neo4j(args.neo4j_uri)
    plans = list(iter_jsonl(args.plans, limit=args.limit))
    contexts = [execute_plan(args.neo4j_uri, args.database, plan) for plan in plans]
    summary = build_summary(contexts, args.neo4j_uri)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.out_dir / "graph_rag_contexts.jsonl", contexts)
    write_json(args.out_dir / "graph_rag_retrieve_summary.json", summary)
    write_markdown(args.out_dir / "graph_rag_retrieve_summary.md", summary, contexts)
    print(json.dumps({"ok": summary["decision"] == "graph_rag_context_ready", "summary": str(args.out_dir / "graph_rag_retrieve_summary.json")}, ensure_ascii=False, indent=2))
    return 0 if summary["decision"] == "graph_rag_context_ready" else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plans", type=Path, default=DEFAULT_PLANS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--neo4j-uri", default=DEFAULT_NEO4J_URI)
    parser.add_argument("--database", default="neo4j")
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
