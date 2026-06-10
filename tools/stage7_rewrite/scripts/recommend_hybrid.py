"""Hybrid recommendation dry-run without mem0 writes or production serving.

This PRD-17 canary fuses graph-similarity recommendations and trending events.
mem0 is explicitly weighted as 0 because the current global gate forbids mem0
writes. No reranker/model/API call is executed.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


DEFAULT_GRAPH_REPORT = Path("reports/graph_recommend_canary_20260515/graph_recommend_canary.json")
DEFAULT_TRENDING_JSONL = Path("reports/trending_index_20260515/trending_index.jsonl")
DEFAULT_OUT_DIR = Path("reports/hybrid_recommend_canary_20260515")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def normalize_scores(rows: list[dict[str, Any]], score_key: str) -> list[dict[str, Any]]:
    max_score = max((float(row.get(score_key) or 0.0) for row in rows), default=0.0)
    result = []
    for row in rows:
        item = dict(row)
        raw = float(item.get(score_key) or 0.0)
        item["normalized_score"] = round(raw / max_score, 6) if max_score > 0 else 0.0
        result.append(item)
    return result


def graph_candidates(graph_report: dict[str, Any], weight: float) -> list[dict[str, Any]]:
    rows = normalize_scores(list(graph_report.get("recommendations") or []), "score")
    result = []
    for row in rows:
        result.append(
            {
                "id": f"graph:{row.get('neighbor_key') or row.get('neighbor')}",
                "type": "graph_neighbor",
                "title": row.get("neighbor"),
                "score": round(weight * row["normalized_score"], 6),
                "source_scores": {"graph": row.get("score"), "graph_normalized": row["normalized_score"], "trending": 0.0, "mem0": 0.0},
                "evidence": {
                    "target": row.get("target"),
                    "shared_events": row.get("shared_events"),
                    "source_article_count": row.get("source_article_count"),
                    "event_names": row.get("event_names") or [],
                },
            }
        )
    return result


def trending_candidates(rows: list[dict[str, Any]], weight: float) -> list[dict[str, Any]]:
    normalized = normalize_scores(rows, "trending_score")
    result = []
    for row in normalized:
        result.append(
            {
                "id": f"trending:{row.get('name')}|{row.get('place')}",
                "type": "trending_event",
                "title": row.get("name"),
                "score": round(weight * row["normalized_score"], 6),
                "source_scores": {"graph": 0.0, "trending": row.get("trending_score"), "trending_normalized": row["normalized_score"], "mem0": 0.0},
                "evidence": {
                    "place": row.get("place"),
                    "event_count": row.get("event_count"),
                    "source_article_count": row.get("source_article_count"),
                    "decay_status": row.get("decay_status"),
                    "time_texts": row.get("time_texts") or [],
                },
            }
        )
    return result


def interleave_by_type(graph_rows: list[dict[str, Any]], trending_rows: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    result = []
    gi = ti = 0
    while len(result) < top_k and (gi < len(graph_rows) or ti < len(trending_rows)):
        if gi < len(graph_rows):
            result.append(graph_rows[gi])
            gi += 1
            if len(result) >= top_k:
                break
        if ti < len(trending_rows):
            result.append(trending_rows[ti])
            ti += 1
    result.sort(key=lambda row: (-row["score"], row["type"], str(row["title"])))
    return result[:top_k]


def diversity_ratio(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    counts = [sum(1 for row in rows if row["type"] == kind) for kind in {row["type"] for row in rows}]
    return round(1.0 - (max(counts) / len(rows)), 4)


def build_report(graph_report: dict[str, Any], trending_rows: list[dict[str, Any]], top_k: int, graph_weight: float, trending_weight: float) -> dict[str, Any]:
    graph_rows = graph_candidates(graph_report, graph_weight)
    trend_rows = trending_candidates(trending_rows, trending_weight)
    final = interleave_by_type(graph_rows, trend_rows, top_k)
    ratio = diversity_ratio(final)
    return {
        "schema_version": "stage7_hybrid_recommendation_canary.v1",
        "generated_at": now_iso(),
        "top_k": top_k,
        "weights": {"graph": graph_weight, "trending": trending_weight, "mem0": 0.0, "reranker": 0.0},
        "graph_input_count": len(graph_rows),
        "trending_input_count": len(trend_rows),
        "recommendation_count": len(final),
        "type_counts": {kind: sum(1 for row in final if row["type"] == kind) for kind in sorted({row["type"] for row in final})},
        "diversity_ratio": ratio,
        "diversity_gate_met": ratio >= 0.5 and len({row["type"] for row in final}) >= 2,
        "decision": "hybrid_recommendations_ready_without_mem0" if final else "hybrid_recommendations_empty",
        "blockers": [
            "mem0 personalization disabled by current write gate",
            "reranker not executed in this dry-run",
            "trending recency limited by missing source-backed time_iso",
        ],
        "recommendations": final,
        "safety": {
            "report_only": True,
            "mem0_write_executed": False,
            "model_call_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
        },
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Hybrid Recommendation Canary",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- recommendation_count: `{report['recommendation_count']}`",
        f"- diversity_ratio: `{report['diversity_ratio']}`",
        f"- diversity_gate_met: `{report['diversity_gate_met']}`",
        f"- weights: `{json.dumps(report['weights'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "| Type | Title | Score |",
        "|---|---|---:|",
    ]
    for row in report["recommendations"]:
        lines.append(f"| `{row['type']}` | `{row['title']}` | {row['score']} |")
    lines.extend(
        [
            "",
            "## Blockers",
            "",
            *[f"- {item}" for item in report["blockers"]],
            "",
            "## Safety",
            "",
            "- Report-only. No mem0, model, Neo4j, Qdrant, SQLite, cloud, or production writes.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    graph_report = read_json(args.graph_report)
    trending_rows = list(iter_jsonl(args.trending_jsonl, limit=args.trending_limit))
    report = build_report(graph_report, trending_rows, args.top_k, args.graph_weight, args.trending_weight)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "hybrid_recommend_canary.json", report)
    write_markdown(args.out_dir / "hybrid_recommend_canary.md", report)
    print(json.dumps({"ok": True, "decision": report["decision"], "recommendation_count": report["recommendation_count"], "report": str(args.out_dir / "hybrid_recommend_canary.json")}, ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-report", type=Path, default=DEFAULT_GRAPH_REPORT)
    parser.add_argument("--trending-jsonl", type=Path, default=DEFAULT_TRENDING_JSONL)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--trending-limit", type=int, default=50)
    parser.add_argument("--graph-weight", type=float, default=0.6)
    parser.add_argument("--trending-weight", type=float, default=0.4)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
