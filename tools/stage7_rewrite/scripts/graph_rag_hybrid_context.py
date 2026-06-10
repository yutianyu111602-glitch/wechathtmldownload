"""Assemble Graph RAG context from read-only Neo4j retrieval rows.

This is a report-only context assembly canary. Qdrant/vector context is marked
as skipped because this gate does not perform embedding/model calls.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


DEFAULT_CONTEXTS = Path("reports/graph_rag_retrieve_20260515/graph_rag_contexts.jsonl")
DEFAULT_OUT_DIR = Path("reports/graph_rag_hybrid_context_20260515")


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


def compact_row(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("event_name"):
        label = row.get("event_name")
        kind = "event"
    elif row.get("entity_name"):
        label = row.get("entity_name")
        kind = "entity"
    else:
        label = row.get("article_title")
        kind = "article"
    return {
        "kind": kind,
        "label": label or "",
        "source_article_uid": row.get("source_article_uid") or "",
        "article_title": row.get("article_title") or "",
        "time_text": row.get("time_text") or "",
        "place": row.get("place") or "",
        "participants_json": row.get("participants_json") or "",
        "entity_type": row.get("entity_type") or "",
        "confidence": row.get("confidence"),
    }


def assemble_context(item: dict[str, Any], max_rows: int) -> dict[str, Any]:
    rows = [compact_row(row) for row in (item.get("rows") or [])[:max_rows]]
    citations = []
    seen = set()
    for row in rows:
        uid = row.get("source_article_uid")
        if uid and uid not in seen:
            seen.add(uid)
            citations.append({"source_article_uid": uid, "article_title": row.get("article_title") or ""})
    return {
        "id": item.get("id"),
        "query": item.get("query"),
        "intent": item.get("intent"),
        "term": item.get("term"),
        "graph_context": rows,
        "graph_context_count": len(rows),
        "vector_context": [],
        "vector_context_status": "skipped_no_embedding_or_qdrant_query_in_this_gate",
        "citations": citations,
        "citation_count": len(citations),
    }


def build_summary(assembled: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "stage7_graph_rag_hybrid_context.v1",
        "generated_at": now_iso(),
        "query_count": len(assembled),
        "contexts_with_graph": sum(1 for item in assembled if item["graph_context_count"] > 0),
        "citation_total": sum(item["citation_count"] for item in assembled),
        "vector_context_status": "skipped_no_embedding_or_qdrant_query_in_this_gate",
        "decision": "graph_context_assembled_without_vector" if assembled else "graph_context_empty",
        "safety": {
            "report_only": True,
            "llm_call_executed": False,
            "embedding_call_executed": False,
            "qdrant_query_executed": False,
            "neo4j_write_executed": False,
            "production_write_executed": False,
        },
    }


def write_markdown(path: Path, summary: dict[str, Any], assembled: list[dict[str, Any]]) -> None:
    lines = [
        "# Graph RAG Hybrid Context",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- query_count: `{summary['query_count']}`",
        f"- contexts_with_graph: `{summary['contexts_with_graph']}`",
        f"- citation_total: `{summary['citation_total']}`",
        f"- vector_context_status: `{summary['vector_context_status']}`",
        "",
        "| ID | Query | Graph Rows | Citations |",
        "|---|---|---:|---:|",
    ]
    for item in assembled:
        lines.append(f"| `{item['id']}` | `{item['query']}` | {item['graph_context_count']} | {item['citation_count']} |")
    lines.extend(["", "## Safety", "", "- Report-only. No LLM, embedding, Qdrant query, Neo4j write, or production write."])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    assembled = [assemble_context(item, args.max_rows) for item in iter_jsonl(args.contexts, limit=args.limit)]
    summary = build_summary(assembled)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.out_dir / "graph_rag_hybrid_contexts.jsonl", assembled)
    write_json(args.out_dir / "graph_rag_hybrid_context_summary.json", summary)
    write_markdown(args.out_dir / "graph_rag_hybrid_context_summary.md", summary, assembled)
    print(json.dumps({"ok": True, "decision": summary["decision"], "summary": str(args.out_dir / "graph_rag_hybrid_context_summary.json")}, ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contexts", type=Path, default=DEFAULT_CONTEXTS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--max-rows", type=int, default=5)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
