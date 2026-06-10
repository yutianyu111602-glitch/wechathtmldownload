"""Deterministic citation-preserving Graph RAG answer draft.

No LLM is called. The script converts assembled graph context into a compact
answer draft so citation coverage can be tested before any paid/model gate.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


DEFAULT_CONTEXTS = Path("reports/graph_rag_hybrid_context_20260515/graph_rag_hybrid_contexts.jsonl")
DEFAULT_OUT_DIR = Path("reports/graph_rag_answer_20260515")


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


def answer_for_context(context: dict[str, Any], max_facts: int) -> dict[str, Any]:
    facts = []
    seen_fact_text = set()
    for row in context.get("graph_context") or []:
        label = row.get("label") or row.get("article_title") or ""
        parts = [label]
        if row.get("place"):
            parts.append(f"地点 {row['place']}")
        if row.get("time_text"):
            parts.append(f"时间 {row['time_text']}")
        fact = "，".join(part for part in parts if part)
        if fact and fact not in seen_fact_text:
            seen_fact_text.add(fact)
            facts.append({"text": fact, "source_article_uid": row.get("source_article_uid") or ""})
        if len(facts) >= max_facts:
            break
    citations = [item for item in (context.get("citations") or []) if item.get("source_article_uid")]
    if facts:
        answer = f"根据 Neo4j staging 检索，找到 {len(facts)} 条可引用线索：" + "；".join(item["text"] for item in facts)
    else:
        answer = "当前 Neo4j staging 检索没有返回可引用线索。"
    return {
        "id": context.get("id"),
        "query": context.get("query"),
        "answer": answer,
        "facts": facts,
        "fact_count": len(facts),
        "citations": citations,
        "citation_count": len(citations),
        "llm_call_executed": False,
        "status": "draft_with_citations" if facts and citations else "draft_empty",
    }


def build_summary(answers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "stage7_graph_rag_answer_draft.v1",
        "generated_at": now_iso(),
        "answer_count": len(answers),
        "answers_with_citations": sum(1 for item in answers if item["citation_count"] > 0),
        "facts_total": sum(item["fact_count"] for item in answers),
        "decision": "answer_drafts_ready_without_llm" if answers else "answer_drafts_empty",
        "safety": {
            "report_only": True,
            "llm_call_executed": False,
            "paid_api_used": False,
            "neo4j_write_executed": False,
            "production_write_executed": False,
        },
    }


def write_markdown(path: Path, summary: dict[str, Any], answers: list[dict[str, Any]]) -> None:
    lines = [
        "# Graph RAG Answer Drafts",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- answer_count: `{summary['answer_count']}`",
        f"- answers_with_citations: `{summary['answers_with_citations']}`",
        f"- llm_call_executed: `False`",
        "",
    ]
    for item in answers[:10]:
        lines.extend(
            [
                f"## {item['id']}",
                "",
                f"- query: `{item['query']}`",
                f"- status: `{item['status']}`",
                f"- citation_count: `{item['citation_count']}`",
                f"- answer: {item['answer']}",
                "",
            ]
        )
    lines.extend(["## Safety", "", "- Deterministic draft only. No LLM, paid API, Neo4j write, or production write."])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    answers = [answer_for_context(context, args.max_facts) for context in iter_jsonl(args.contexts, limit=args.limit)]
    summary = build_summary(answers)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.out_dir / "graph_rag_answer_drafts.jsonl", answers)
    write_json(args.out_dir / "graph_rag_answer_summary.json", summary)
    write_markdown(args.out_dir / "graph_rag_answer_summary.md", summary, answers)
    print(json.dumps({"ok": True, "decision": summary["decision"], "summary": str(args.out_dir / "graph_rag_answer_summary.json")}, ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contexts", type=Path, default=DEFAULT_CONTEXTS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--max-facts", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
