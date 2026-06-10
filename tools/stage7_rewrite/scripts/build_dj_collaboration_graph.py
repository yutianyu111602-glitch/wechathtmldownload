"""Build a report-only participant collaboration graph from Stage7 event cards.

The graph is a recommendation dry-run artifact for PRD-17. It reads the local
consumer release pack, derives co-appearance pairs from event participants, and
writes reports only. It does not mutate Neo4j, Qdrant, mem0, SQLite, or any
production service.
"""

from __future__ import annotations

import argparse
import itertools
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


DEFAULT_EVENTS_JSONL = Path("reports/consumer_release_pack_full_unknown_time_20260514/events.jsonl")
DEFAULT_OUT_DIR = Path("reports/dj_collab_graph_20260515")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


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


def iter_jsonl(path: Path, limit: int = 0) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle, start=1):
            if limit and idx > limit:
                break
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def norm_name(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def node_key(name: str) -> str:
    return norm_name(name).casefold()


def participants(row: dict[str, Any], max_per_event: int = 24) -> list[str]:
    values = row.get("participants")
    if not isinstance(values, list):
        return []
    seen = set()
    result = []
    for value in values:
        name = norm_name(value)
        key = node_key(name)
        if not name or key in seen:
            continue
        seen.add(key)
        result.append(name)
        if len(result) >= max_per_event:
            break
    return result


def confidence(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def build_graph(rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    edges: dict[tuple[str, str], dict[str, Any]] = {}
    display_names: dict[str, str] = {}
    node_articles: dict[str, set[str]] = defaultdict(set)
    event_rows = 0
    usable_events = 0
    participant_mentions = 0
    for row in rows:
        event_rows += 1
        people = participants(row)
        participant_mentions += len(people)
        if len(people) < 2:
            continue
        usable_events += 1
        article_uid = norm_name(row.get("source_article_uid"))
        event_name = norm_name(row.get("name"))
        for name in people:
            key = node_key(name)
            display_names.setdefault(key, name)
            if article_uid:
                node_articles[key].add(article_uid)
        for left, right in itertools.combinations(people, 2):
            a, b = sorted((node_key(left), node_key(right)))
            edge = edges.setdefault(
                (a, b),
                {
                    "source": display_names.get(a, left),
                    "target": display_names.get(b, right),
                    "source_key": a,
                    "target_key": b,
                    "shared_events": 0,
                    "source_articles": [],
                    "event_names": [],
                    "places": [],
                    "time_texts": [],
                    "confidence_sum": 0.0,
                },
            )
            edge["shared_events"] += 1
            edge["confidence_sum"] += confidence(row.get("confidence"))
            for field, value in (
                ("source_articles", article_uid),
                ("event_names", event_name),
                ("places", norm_name(row.get("place"))),
                ("time_texts", norm_name(row.get("time_iso") or row.get("time_text"))),
            ):
                if value and value not in edge[field]:
                    edge[field].append(value)
    edge_rows = []
    weighted_degree: Counter[str] = Counter()
    for edge in edges.values():
        edge["source_articles"] = edge["source_articles"][:5]
        edge["event_names"] = edge["event_names"][:5]
        edge["places"] = edge["places"][:5]
        edge["time_texts"] = edge["time_texts"][:5]
        edge["avg_confidence"] = round(edge["confidence_sum"] / max(edge["shared_events"], 1), 4)
        edge["score"] = round(edge["shared_events"] * max(edge["avg_confidence"], 0.1), 4)
        weighted_degree[edge["source_key"]] += edge["shared_events"]
        weighted_degree[edge["target_key"]] += edge["shared_events"]
        edge_rows.append(edge)
    edge_rows.sort(key=lambda row: (-row["score"], -row["shared_events"], row["source"], row["target"]))
    summary = {
        "schema_version": "stage7_dj_collaboration_graph.v1",
        "generated_at": now_iso(),
        "event_rows": event_rows,
        "usable_events": usable_events,
        "participant_mentions": participant_mentions,
        "node_count": len(display_names),
        "edge_count": len(edge_rows),
        "top_nodes": [
            {
                "name": display_names.get(key, key),
                "key": key,
                "weighted_degree": int(score),
                "source_article_count": len(node_articles.get(key, set())),
            }
            for key, score in weighted_degree.most_common(20)
        ],
        "safety": {
            "report_only": True,
            "mem0_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
        },
    }
    return edge_rows, summary


def write_markdown(path: Path, summary: dict[str, Any], edges: list[dict[str, Any]]) -> None:
    lines = [
        "# DJ Collaboration Graph",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- event_rows: `{summary['event_rows']}`",
        f"- usable_events: `{summary['usable_events']}`",
        f"- node_count: `{summary['node_count']}`",
        f"- edge_count: `{summary['edge_count']}`",
        "",
        "## Top Edges",
        "",
        "| Source | Target | Shared Events | Score | Articles |",
        "|---|---|---:|---:|---:|",
    ]
    for row in edges[:20]:
        lines.append(
            f"| `{row['source']}` | `{row['target']}` | {row['shared_events']} | {row['score']} | {len(row['source_articles'])} |"
        )
    lines.extend(["", "## Safety", "", "- Report-only. No mem0, Neo4j, Qdrant, SQLite, cloud, or production writes."])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    edges, summary = build_graph(iter_jsonl(args.events_jsonl, limit=args.limit))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.out_dir / "dj_collab_edges.jsonl", edges)
    write_json(args.out_dir / "dj_collab_graph_summary.json", summary)
    write_markdown(args.out_dir / "dj_collab_graph_summary.md", summary, edges)
    print(json.dumps({"ok": True, "edge_count": len(edges), "summary": str(args.out_dir / "dj_collab_graph_summary.json")}, ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events-jsonl", type=Path, default=DEFAULT_EVENTS_JSONL)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
