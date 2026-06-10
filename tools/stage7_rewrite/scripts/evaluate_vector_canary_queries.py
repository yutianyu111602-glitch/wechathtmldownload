"""Evaluate local vector canary artifacts without DB writes.

The script reads one or more `run_full_vectorize.py --mode build` output
directories, embeds a small query set with the same local model, and writes a
JSON/Markdown smoke report. It never touches Qdrant, Neo4j, production SQLite,
or source archive trees.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from stage7_runtime_guard import enforce_native_heavy_python_guard


DEFAULT_QUERIES = [
    {"id": "q_venue_shanghai", "query": "上海 俱乐部 电子音乐 活动 阵容"},
    {"id": "q_bj_dada", "query": "北京 Dada 酒吧 DJ 活动"},
    {"id": "q_shenzhen_oil", "query": "深圳 OIL CLUB 电子音乐 活动"},
    {"id": "q_hakka_wine", "query": "院吧 Hakka Bar 葡萄酒 酒单"},
    {"id": "q_bandcamp_soundcloud", "query": "DJ SoundCloud Bandcamp Linktree profile"},
    {"id": "q_weekend_party", "query": "本周末 派对 lineup 阵容 场地"},
]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def l2_normalize(matrix: Any) -> Any:
    import numpy as np

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def load_queries(path: Path | None) -> list[dict[str, Any]]:
    if not path:
        return list(DEFAULT_QUERIES)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("queries", [])
        return [dict(item) for item in data]
    return read_jsonl(path)


def build_self_queries(cards: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if limit <= 0 or not cards:
        return []
    step = max(1, math.floor(len(cards) / limit))
    queries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx in range(0, len(cards), step):
        card = cards[idx]
        text = str(card.get("text", "")).strip()
        card_id = str(card.get("id", "")).strip()
        if not text or not card_id or card_id in seen:
            continue
        seen.add(card_id)
        queries.append(
            {
                "id": f"self_{len(queries):03d}",
                "query": text,
                "expected_card_id": card_id,
                "source": "self_alignment",
            }
        )
        if len(queries) >= limit:
            break
    return queries


def top_hits(sim_row: Any, cards: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    import numpy as np

    top_idx = np.argsort(-sim_row)[:top_k]
    hits = []
    for rank, idx in enumerate(top_idx, start=1):
        card = cards[int(idx)]
        hits.append(
            {
                "rank": rank,
                "score": round(float(sim_row[int(idx)]), 6),
                "id": card.get("id"),
                "type": card.get("type"),
                "title": card.get("title"),
                "name": card.get("name"),
                "source_account": card.get("source_account"),
                "article_uid": card.get("article_uid"),
                "text": str(card.get("text", ""))[:240],
            }
        )
    return hits


def evaluate_vector_dir(vector_dir: Path, queries: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    enforce_native_heavy_python_guard(f"evaluate_vector_canary_queries.evaluate_vector_dir:{vector_dir}")
    import numpy as np
    from sentence_transformers import SentenceTransformer

    metadata = read_json(vector_dir / "metadata.json")
    cards = read_jsonl(vector_dir / "card_texts.jsonl")
    vectors = np.load(vector_dir / "vectors.npy")
    if len(cards) != vectors.shape[0]:
        raise ValueError(f"{vector_dir}: card count {len(cards)} != vector rows {vectors.shape[0]}")

    model_name = args.model or metadata.get("model") or "Qwen/Qwen3-Embedding-4B"
    truncate_dim = metadata.get("truncate_dim")
    if truncate_dim in (0, "0", ""):
        truncate_dim = None

    model = SentenceTransformer(model_name, device=args.device)
    query_texts = [str(item["query"]) for item in queries]
    query_vectors = model.encode(
        query_texts,
        batch_size=args.batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
        truncate_dim=truncate_dim,
    )

    vectors_n = l2_normalize(vectors.astype("float32"))
    query_vectors_n = l2_normalize(query_vectors.astype("float32"))
    sims = query_vectors_n @ vectors_n.T

    query_results = []
    self_total = 0
    self_top1 = 0
    self_top5 = 0
    for query, sim_row in zip(queries, sims):
        hits = top_hits(sim_row, cards, args.top_k)
        expected = query.get("expected_card_id")
        expected_rank = None
        if expected:
            self_total += 1
            for hit in hits:
                if hit.get("id") == expected:
                    expected_rank = hit["rank"]
                    break
            if expected_rank == 1:
                self_top1 += 1
            if expected_rank is not None and expected_rank <= min(5, args.top_k):
                self_top5 += 1
        query_results.append(
            {
                "id": query.get("id"),
                "query": query.get("query"),
                "source": query.get("source", "fixed"),
                "expected_card_id": expected,
                "expected_rank": expected_rank,
                "top_hits": hits,
            }
        )

    return {
        "vector_dir": str(vector_dir),
        "model": model_name,
        "dim": int(vectors.shape[1]),
        "card_count": int(vectors.shape[0]),
        "truncate_dim": truncate_dim,
        "self_query_count": self_total,
        "self_top1_rate": round(self_top1 / max(self_total, 1), 4),
        "self_top5_rate": round(self_top5 / max(self_total, 1), 4),
        "queries": query_results,
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Vector Canary Query Eval",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- execution_host_policy: `{report['execution_host_policy']}`",
        f"- query_count: `{report['query_count']}`",
        "",
        "## Summary",
        "",
        "| vector_dir | dim | cards | self_top1 | self_top5 |",
        "|---|---:|---:|---:|---:|",
    ]
    for result in report["results"]:
        lines.append(
            f"| `{result['vector_dir']}` | {result['dim']} | {result['card_count']} | "
            f"{result['self_top1_rate']} | {result['self_top5_rate']} |"
        )
    lines.extend(["", "## Fixed Query Top Hits", ""])
    for result in report["results"]:
        lines.append(f"### {result['dim']}d")
        for query in result["queries"]:
            if query.get("source") == "self_alignment":
                continue
            lines.append(f"- `{query['id']}` {query['query']}")
            for hit in query["top_hits"][:3]:
                label = hit.get("title") or hit.get("name") or hit.get("text")
                lines.append(f"  - rank {hit['rank']} score {hit['score']}: {label}")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate local vector canary query recall without DB writes.")
    parser.add_argument("--vector-dir", action="append", required=True, help="Directory containing vectors.npy/card_texts.jsonl/metadata.json")
    parser.add_argument("--queries", type=Path, help="Optional JSON/JSONL query file")
    parser.add_argument("--out-dir", type=Path, default=Path("reports/vector_canary_query_eval_20260514"))
    parser.add_argument("--model", default="", help="Override query embedding model; defaults to metadata model")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--self-query-count", type=int, default=24)
    args = parser.parse_args()

    vector_dirs = [Path(item) for item in args.vector_dir]
    args.out_dir.mkdir(parents=True, exist_ok=True)

    fixed_queries = load_queries(args.queries)
    first_cards = read_jsonl(vector_dirs[0] / "card_texts.jsonl")
    queries = fixed_queries + build_self_queries(first_cards, args.self_query_count)

    report = {
        "schema_version": "vector_canary_query_eval.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "execution_host_policy": "local RTX 4090 only; no Mac endpoints, DB writes, or D: scans",
        "query_count": len(queries),
        "fixed_query_count": len(fixed_queries),
        "self_query_count": len(queries) - len(fixed_queries),
        "results": [evaluate_vector_dir(path, queries, args) for path in vector_dirs],
    }
    json_path = args.out_dir / "vector_canary_query_eval.json"
    md_path = args.out_dir / "vector_canary_query_eval.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    write_markdown(md_path, report)
    print(json.dumps({"ok": True, "json": str(json_path), "markdown": str(md_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
