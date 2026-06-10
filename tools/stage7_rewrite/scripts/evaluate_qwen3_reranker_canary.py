"""Run a bounded Qwen3 reranker canary over local vector artifacts.

This script reads local `run_full_vectorize.py` artifacts, retrieves dense
top-N candidates, and reranks only those candidates with
`Qwen/Qwen3-Reranker-4B`. It writes local JSON/Markdown reports only.
"""

from __future__ import annotations

import argparse
import gc
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from stage7_runtime_guard import enforce_native_heavy_python_guard


DEFAULT_VECTOR_DIR = Path("reports/vector_full_qwen3_4b_1024_20260514")
DEFAULT_OUT_DIR = Path("reports/reranker_canary_qwen3_4b_20260514")
DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-4B"
DEFAULT_RERANKER_MODEL = "Qwen/Qwen3-Reranker-4B"
DEFAULT_INSTRUCTION = (
    "Given a query about underground electronic music events, DJs, venues, labels, "
    "radio shows, social profiles, or WeChat articles, retrieve the most relevant Stage7 cards."
)

FIXED_QUERIES = [
    {"id": "q_venue_shanghai", "query": "上海 俱乐部 电子音乐 活动 阵容", "source": "fixed"},
    {"id": "q_bj_dada", "query": "北京 Dada 酒吧 DJ 活动", "source": "fixed"},
    {"id": "q_shenzhen_oil", "query": "深圳 OIL CLUB 电子音乐 活动", "source": "fixed"},
    {"id": "q_hakka_wine", "query": "院吧 Hakka Bar 葡萄酒 酒单", "source": "fixed"},
    {"id": "q_bandcamp_soundcloud", "query": "DJ SoundCloud Bandcamp Linktree profile", "source": "fixed"},
    {"id": "q_weekend_party", "query": "本周末 派对 lineup 阵容 场地", "source": "fixed"},
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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def top_candidate_indices(sim_row: Any, candidate_k: int) -> list[int]:
    import numpy as np

    if candidate_k <= 0:
        return []
    limit = min(candidate_k, int(sim_row.shape[0]))
    if limit == 0:
        return []
    partial = np.argpartition(-sim_row, limit - 1)[:limit]
    ordered = partial[np.argsort(-sim_row[partial])]
    return [int(idx) for idx in ordered]


def rank_hits(candidates: list[dict[str, Any]], scores: list[float]) -> list[dict[str, Any]]:
    ranked = []
    for candidate, score in zip(candidates, scores):
        row = dict(candidate)
        row["rerank_score"] = round(float(score), 6)
        ranked.append(row)
    ranked.sort(key=lambda item: item["rerank_score"], reverse=True)
    for rank, row in enumerate(ranked, start=1):
        row["rerank_rank"] = rank
    return ranked


def first_expected_rank(hits: list[dict[str, Any]], expected_card_id: str | None) -> int | None:
    if not expected_card_id:
        return None
    for hit in hits:
        if hit.get("id") == expected_card_id:
            return int(hit.get("rerank_rank") or hit.get("dense_rank") or 0)
    return None


def normalize_signature_part(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def hit_signature(hit: dict[str, Any]) -> tuple[str, str]:
    return (
        normalize_signature_part(hit.get("type")),
        normalize_signature_part(hit.get("title") or hit.get("name") or hit.get("text")),
    )


def dedupe_hits(hits: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for hit in hits:
        signature = hit_signature(hit)
        if signature in seen:
            continue
        seen.add(signature)
        row = dict(hit)
        row["diverse_rank"] = len(deduped) + 1
        deduped.append(row)
        if len(deduped) >= limit:
            break
    return deduped


def first_expected_signature_rank(hits: list[dict[str, Any]], expected_card: dict[str, Any] | None) -> int | None:
    if not expected_card:
        return None
    expected_signature = hit_signature(expected_card)
    for rank, hit in enumerate(hits, start=1):
        if hit_signature(hit) == expected_signature:
            return rank
    return None


def card_label(card: dict[str, Any]) -> str:
    return str(card.get("title") or card.get("name") or card.get("text") or "")[:160]


def load_queries(path: Path | None) -> list[dict[str, Any]]:
    if not path:
        return [dict(item) for item in FIXED_QUERIES]
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("queries", [])
        return [dict(item) for item in data]
    return read_jsonl(path)


def build_self_queries(cards: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count <= 0 or not cards:
        return []
    step = max(1, len(cards) // count)
    queries = []
    seen: set[str] = set()
    for idx in range(0, len(cards), step):
        card = cards[idx]
        card_id = str(card.get("id") or "")
        text = str(card.get("text") or "")
        if not card_id or not text or card_id in seen:
            continue
        seen.add(card_id)
        queries.append(
            {
                "id": f"self_{len(queries):03d}",
                "query": text,
                "source": "self_alignment",
                "expected_card_id": card_id,
            }
        )
        if len(queries) >= count:
            break
    return queries


def format_rerank_query(query: str, instruction: str) -> str:
    if not instruction:
        return query
    return f"<Instruct>: {instruction}\n<Query>: {query}"


def candidate_rows(indices: list[int], sims: Any, cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for rank, idx in enumerate(indices, start=1):
        card = cards[idx]
        rows.append(
            {
                "dense_rank": rank,
                "dense_score": round(float(sims[idx]), 6),
                "id": card.get("id"),
                "type": card.get("type"),
                "title": card.get("title"),
                "name": card.get("name"),
                "article_uid": card.get("article_uid"),
                "source_account": card.get("source_account"),
                "text": str(card.get("text") or "")[:500],
            }
        )
    return rows


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Qwen3 Reranker Canary",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- vector_dir: `{report['vector_dir']}`",
        f"- embedding_model: `{report['embedding_model']}`",
        f"- reranker_model: `{report['reranker_model']}`",
        f"- query_count: `{report['query_count']}`",
        f"- candidate_k: `{report['candidate_k']}`",
        f"- rerank_k: `{report['rerank_k']}`",
        f"- self_top1_rate: `{report['self_top1_rate']}`",
        f"- self_top5_rate: `{report['self_top5_rate']}`",
        f"- self_signature_top1_rate: `{report['self_signature_top1_rate']}`",
        f"- self_signature_top5_rate: `{report['self_signature_top5_rate']}`",
        f"- avg_unique_signature_top10: `{report['avg_unique_signature_top10']}`",
        "",
        "## Query Results",
        "",
    ]
    for query in report["queries"]:
        lines.append(f"### {query['id']}: {query['query']}")
        lines.append(f"- source: `{query.get('source')}`")
        if query.get("expected_card_id"):
            lines.append(f"- expected_card_id: `{query['expected_card_id']}`, expected_rerank_rank: `{query.get('expected_rerank_rank')}`")
            lines.append(f"- expected_signature_rank: `{query.get('expected_signature_rank')}`")
        lines.append("")
        lines.append("| rank | score | dense_rank | kind | label |")
        lines.append("|---:|---:|---:|---|---|")
        for hit in query["reranked_hits"][: report["rerank_k"]]:
            label = card_label(hit).replace("|", "/")
            lines.append(
                f"| {hit['rerank_rank']} | {hit['rerank_score']} | {hit['dense_rank']} | "
                f"{hit.get('type', '')} | {label} |"
            )
        lines.append("")
        if query.get("diverse_hits"):
            lines.append("Diverse top hits:")
            lines.append("")
            lines.append("| diverse_rank | score | original_rank | kind | label |")
            lines.append("|---:|---:|---:|---|---|")
            for hit in query["diverse_hits"][: report["rerank_k"]]:
                label = card_label(hit).replace("|", "/")
                lines.append(
                    f"| {hit['diverse_rank']} | {hit['rerank_score']} | {hit['rerank_rank']} | "
                    f"{hit.get('type', '')} | {label} |"
                )
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def dry_run(args: argparse.Namespace, metadata: dict[str, Any]) -> int:
    plan = {
        "schema_version": "qwen3_reranker_canary_plan.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "dry-run",
        "vector_dir": str(args.vector_dir),
        "out_dir": str(args.out_dir),
        "card_count": metadata.get("card_count"),
        "dim": metadata.get("dim"),
        "embedding_shape": metadata.get("embedding_shape"),
        "embedding_model": args.embedding_model,
        "reranker_model": args.reranker_model,
        "candidate_k": args.candidate_k,
        "rerank_k": args.rerank_k,
        "self_query_count": args.self_query_count,
        "execution_host_policy": "local RTX 4090 only; no Mac endpoints, DB writes, or D: scans",
    }
    write_json(args.out_dir / "reranker_canary_plan.json", plan)
    print(json.dumps({"ok": True, **plan}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def run_build(args: argparse.Namespace, metadata: dict[str, Any]) -> int:
    enforce_native_heavy_python_guard("evaluate_qwen3_reranker_canary.run_build")
    import numpy as np
    import torch
    from sentence_transformers import CrossEncoder, SentenceTransformer

    started_all = time.perf_counter()
    cards = read_jsonl(args.vector_dir / "card_texts.jsonl")
    cards_by_id = {str(card.get("id")): card for card in cards if card.get("id")}
    vectors = np.load(args.vector_dir / "vectors.npy", mmap_mode="r")
    if len(cards) != int(vectors.shape[0]):
        raise ValueError(f"card_texts count {len(cards)} != vector rows {vectors.shape[0]}")

    queries = load_queries(args.queries) + build_self_queries(cards, args.self_query_count)
    query_texts = [str(item["query"]) for item in queries]

    embed_started = time.perf_counter()
    embedder = SentenceTransformer(args.embedding_model, device=args.device)
    query_vectors = embedder.encode(
        query_texts,
        batch_size=args.embedding_batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
        truncate_dim=args.truncate_dim or None,
    )
    embed_sec = time.perf_counter() - embed_started
    del embedder
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
    gc.collect()

    dense_started = time.perf_counter()
    query_vectors = np.asarray(query_vectors, dtype="float32")
    dense_results = []
    for query, query_vector in zip(queries, query_vectors):
        sims = np.asarray(vectors @ query_vector, dtype="float32")
        indices = top_candidate_indices(sims, args.candidate_k)
        dense_results.append((query, candidate_rows(indices, sims, cards)))
    dense_sec = time.perf_counter() - dense_started

    rerank_started = time.perf_counter()
    reranker = CrossEncoder(args.reranker_model, device=args.device)
    query_reports = []
    self_total = 0
    self_top1 = 0
    self_top5 = 0
    self_signature_top1 = 0
    self_signature_top5 = 0
    unique_signature_top10_total = 0
    pair_count = 0
    for query, candidates in dense_results:
        rerank_query = format_rerank_query(str(query["query"]), args.instruction)
        pairs = [(rerank_query, str(candidate["text"])) for candidate in candidates]
        pair_count += len(pairs)
        scores = reranker.predict(pairs, batch_size=args.rerank_batch_size, show_progress_bar=False)
        ranked = rank_hits(candidates, [float(score) for score in scores])
        expected_rank = first_expected_rank(ranked, query.get("expected_card_id"))
        expected_signature_rank = first_expected_signature_rank(ranked, cards_by_id.get(str(query.get("expected_card_id"))))
        top10_signatures = {hit_signature(hit) for hit in ranked[: args.rerank_k]}
        unique_signature_top10_total += len(top10_signatures)
        diverse_hits = dedupe_hits(ranked, args.rerank_k)
        if query.get("source") == "self_alignment":
            self_total += 1
            if expected_rank == 1:
                self_top1 += 1
            if expected_rank is not None and expected_rank <= 5:
                self_top5 += 1
            if expected_signature_rank == 1:
                self_signature_top1 += 1
            if expected_signature_rank is not None and expected_signature_rank <= 5:
                self_signature_top5 += 1
        query_reports.append(
            {
                "id": query.get("id"),
                "query": query.get("query"),
                "source": query.get("source", "fixed"),
                "expected_card_id": query.get("expected_card_id"),
                "expected_rerank_rank": expected_rank,
                "expected_signature_rank": expected_signature_rank,
                "reranked_hits": ranked[: args.rerank_k],
                "reranked_hits_all": ranked,
                "diverse_hits": diverse_hits,
                "unique_signature_top10": len(top10_signatures),
            }
        )
    rerank_sec = time.perf_counter() - rerank_started
    peak_gb = round(torch.cuda.max_memory_allocated() / 1024**3, 3) if torch.cuda.is_available() else None
    del reranker
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()

    report = {
        "schema_version": "qwen3_reranker_canary.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "execution_host_policy": "local RTX 4090 only; no Mac endpoints, DB writes, or D: scans",
        "vector_dir": str(args.vector_dir),
        "card_count": metadata.get("card_count"),
        "dim": metadata.get("dim"),
        "embedding_model": args.embedding_model,
        "reranker_model": args.reranker_model,
        "instruction": args.instruction,
        "candidate_k": args.candidate_k,
        "rerank_k": args.rerank_k,
        "query_count": len(queries),
        "pair_count": pair_count,
        "embedding_query_sec": round(embed_sec, 3),
        "dense_retrieval_sec": round(dense_sec, 3),
        "rerank_sec": round(rerank_sec, 3),
        "total_sec": round(time.perf_counter() - started_all, 3),
        "vram_peak_gb": peak_gb,
        "self_query_count": self_total,
        "self_top1_rate": round(self_top1 / max(self_total, 1), 4),
        "self_top5_rate": round(self_top5 / max(self_total, 1), 4),
        "self_signature_top1_rate": round(self_signature_top1 / max(self_total, 1), 4),
        "self_signature_top5_rate": round(self_signature_top5 / max(self_total, 1), 4),
        "avg_unique_signature_top10": round(unique_signature_top10_total / max(len(queries), 1), 3),
        "queries": query_reports,
    }
    write_json(args.out_dir / "reranker_canary.json", report)
    write_markdown(args.out_dir / "reranker_canary.md", report)
    print(json.dumps({"ok": True, "json": str(args.out_dir / "reranker_canary.json"), "markdown": str(args.out_dir / "reranker_canary.md")}, ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vector-dir", type=Path, default=DEFAULT_VECTOR_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--mode", choices=["dry-run", "build"], default="dry-run")
    parser.add_argument("--queries", type=Path)
    parser.add_argument("--candidate-k", type=int, default=50)
    parser.add_argument("--rerank-k", type=int, default=10)
    parser.add_argument("--self-query-count", type=int, default=6)
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--instruction", default=DEFAULT_INSTRUCTION)
    parser.add_argument("--truncate-dim", type=int, default=1024)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--embedding-batch-size", type=int, default=8)
    parser.add_argument("--rerank-batch-size", type=int, default=4)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    metadata_path = args.vector_dir / "metadata.json"
    if not metadata_path.exists():
        raise SystemExit(f"metadata not found: {metadata_path}")
    if not (args.vector_dir / "vectors.npy").exists():
        raise SystemExit(f"vectors.npy not found under {args.vector_dir}")
    if not (args.vector_dir / "card_texts.jsonl").exists():
        raise SystemExit(f"card_texts.jsonl not found under {args.vector_dir}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    metadata = read_json(metadata_path)
    if args.mode == "dry-run":
        return dry_run(args, metadata)
    return run_build(args, metadata)


if __name__ == "__main__":
    raise SystemExit(main())
