"""Recommend similar participants from a report-only collaboration graph."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


DEFAULT_GRAPH_JSONL = Path("reports/dj_collab_graph_20260515/dj_collab_edges.jsonl")
DEFAULT_OUT_DIR = Path("reports/graph_recommend_canary_20260515")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def norm_name(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def node_key(name: str) -> str:
    return norm_name(name).casefold()


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def select_default_target(edges: list[dict[str, Any]]) -> str:
    degree: Counter[str] = Counter()
    names: dict[str, str] = {}
    for row in edges:
        for key_field, name_field in (("source_key", "source"), ("target_key", "target")):
            key = str(row.get(key_field) or "")
            if not key:
                continue
            degree[key] += int(row.get("shared_events") or 0)
            names.setdefault(key, str(row.get(name_field) or key))
    if not degree:
        return ""
    key, _ = degree.most_common(1)[0]
    return names.get(key, key)


def recommendations(edges: list[dict[str, Any]], target: str, top_k: int) -> list[dict[str, Any]]:
    key = node_key(target)
    rows = []
    for row in edges:
        if row.get("source_key") == key:
            neighbor = row.get("target")
            neighbor_key = row.get("target_key")
        elif row.get("target_key") == key:
            neighbor = row.get("source")
            neighbor_key = row.get("source_key")
        else:
            continue
        shared_events = int(row.get("shared_events") or 0)
        article_count = len(row.get("source_articles") or [])
        score = float(row.get("score") or 0.0) + 0.05 * article_count
        rows.append(
            {
                "target": target,
                "neighbor": neighbor,
                "neighbor_key": neighbor_key,
                "score": round(score, 4),
                "shared_events": shared_events,
                "source_article_count": article_count,
                "event_names": (row.get("event_names") or [])[:5],
                "places": (row.get("places") or [])[:5],
                "time_texts": (row.get("time_texts") or [])[:5],
            }
        )
    rows.sort(key=lambda item: (-item["score"], -item["shared_events"], item["neighbor"]))
    return rows[:top_k]


def build_report(edges: list[dict[str, Any]], target: str, top_k: int) -> dict[str, Any]:
    actual_target = target or select_default_target(edges)
    recs = recommendations(edges, actual_target, top_k) if actual_target else []
    return {
        "schema_version": "stage7_graph_similarity_recommendation.v1",
        "generated_at": now_iso(),
        "target": actual_target,
        "top_k": top_k,
        "edge_count": len(edges),
        "recommendation_count": len(recs),
        "recommendations": recs,
        "decision": "graph_recommendations_ready" if recs else "graph_recommendations_empty",
        "safety": {
            "report_only": True,
            "mem0_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
        },
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Graph Similarity Recommendation Canary",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- target: `{report['target']}`",
        f"- recommendation_count: `{report['recommendation_count']}`",
        "",
        "| Neighbor | Score | Shared Events | Articles |",
        "|---|---:|---:|---:|",
    ]
    for row in report["recommendations"]:
        lines.append(f"| `{row['neighbor']}` | {row['score']} | {row['shared_events']} | {row['source_article_count']} |")
    lines.extend(["", "## Safety", "", "- Report-only. No mem0, Neo4j, Qdrant, SQLite, cloud, or production writes."])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    edges = list(iter_jsonl(args.graph_jsonl))
    report = build_report(edges, args.target, args.top_k)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "graph_recommend_canary.json", report)
    write_markdown(args.out_dir / "graph_recommend_canary.md", report)
    print(json.dumps({"ok": True, "decision": report["decision"], "target": report["target"], "report": str(args.out_dir / "graph_recommend_canary.json")}, ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-jsonl", type=Path, default=DEFAULT_GRAPH_JSONL)
    parser.add_argument("--target", default="")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
