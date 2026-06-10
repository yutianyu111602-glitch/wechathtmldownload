"""Run a bounded serving-style retrieval smoke against Qdrant full staging.

Pipeline: Qwen3 query embedding -> Qdrant dense top-K from the three full-staging
collections -> Qwen3-Reranker-4B -> deterministic diversity policy.

This writes local reports only. It does not write Qdrant points, update
collection config, promote aliases, start Neo4j, touch production SQLite, call
paid APIs, or scan D:.
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import numpy as np
import requests

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from apply_retrieval_policy_canary import apply_policy, parse_type_targets  # noqa: E402
from evaluate_qwen3_reranker_canary import (  # noqa: E402
    FIXED_QUERIES,
    card_label,
    first_expected_rank,
    first_expected_signature_rank,
    format_rerank_query,
    hit_signature,
    rank_hits,
)
from stage7_runtime_guard import enforce_native_heavy_python_guard


DEFAULT_VECTOR_DIR = Path("reports/vector_full_qwen3_4b_1024_20260514")
DEFAULT_OUT_DIR = Path("reports/qdrant_serving_retrieval_smoke_20260514")
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-4B"
DEFAULT_RERANKER_MODEL = "Qwen/Qwen3-Reranker-4B"
DEFAULT_TYPE_TARGETS = "event=4,entity=4,article=2"
DEFAULT_INSTRUCTION = (
    "Given a query about underground electronic music events, DJs, venues, labels, "
    "radio shows, social profiles, or WeChat articles, retrieve the most relevant Stage7 cards."
)
KINDS = ("article", "entity", "event")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def read_jsonl_iter(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle):
            stripped = line.strip()
            if stripped:
                row = json.loads(stripped)
                row["_vector_index"] = idx
                yield row


def require_local_qdrant(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"Qdrant URL must be local for this smoke check: {url}")


def slug_model(model: str) -> str:
    text = model.lower().replace("qwen/", "").replace("-", "_").replace("/", "_")
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in text).strip("_")


def collection_name(kind: str, model: str, dim: int, stamp: str) -> str:
    return f"wechat_stage7_{kind}_{slug_model(model)}_{dim}_{stamp}_full_staging"


def collection_info(qdrant_url: str, name: str) -> dict[str, Any]:
    response = requests.get(f"{qdrant_url.rstrip('/')}/collections/{quote(name)}", timeout=30)
    if response.status_code >= 400:
        raise RuntimeError(f"GET collection {name} failed {response.status_code}: {response.text[:500]}")
    return response.json().get("result") or {}


def collection_health(qdrant_url: str, name: str) -> dict[str, Any]:
    info = collection_info(qdrant_url, name)
    optimizer_status = info.get("optimizer_status")
    return {
        "status": info.get("status"),
        "optimizer_status": optimizer_status,
        "healthy": info.get("status") == "green" and (optimizer_status == "ok" or optimizer_status is None),
        "points_count": int(info.get("points_count") or 0),
        "indexed_vectors_count": int(info.get("indexed_vectors_count") or 0),
        "segments_count": int(info.get("segments_count") or 0),
    }


def select_self_queries(card_texts_path: Path, count: int) -> list[dict[str, Any]]:
    if count <= 0:
        return []
    per_kind = max(1, count // len(KINDS))
    selected_counts: Counter[str] = Counter()
    rows = []
    for row in read_jsonl_iter(card_texts_path):
        kind = str(row.get("type") or "")
        if kind not in KINDS or selected_counts[kind] >= per_kind:
            continue
        text = str(row.get("text") or "")
        card_id = str(row.get("id") or "")
        if text and card_id:
            selected_counts[kind] += 1
            rows.append(
                {
                    "id": f"self_{kind}_{selected_counts[kind] - 1:03d}",
                    "query": text,
                    "source": "self_alignment",
                    "expected_card_id": card_id,
                    "expected_card": {
                        "id": card_id,
                        "type": row.get("type"),
                        "title": row.get("title"),
                        "name": row.get("name"),
                        "text": row.get("text"),
                    },
                }
            )
        if len(rows) >= count:
            break
    return rows


def qdrant_search(qdrant_url: str, collection: str, vector: list[float], limit: int) -> tuple[list[dict[str, Any]], float]:
    base = qdrant_url.rstrip("/")
    started = time.perf_counter()
    response = requests.post(
        f"{base}/collections/{quote(collection)}/points/search",
        json={"vector": vector, "limit": limit, "with_payload": True},
        timeout=240,
    )
    if response.status_code == 404:
        response = requests.post(
            f"{base}/collections/{quote(collection)}/points/query",
            json={"query": vector, "limit": limit, "with_payload": True},
            timeout=240,
        )
    elapsed = time.perf_counter() - started
    if response.status_code >= 400:
        raise RuntimeError(f"Qdrant search failed {response.status_code}: {response.text[:500]}")
    result = response.json().get("result")
    if isinstance(result, dict):
        result = result.get("points")
    return result or [], elapsed


def qdrant_hit_to_candidate(hit: dict[str, Any], collection_kind: str) -> dict[str, Any]:
    payload = hit.get("payload") or {}
    return {
        "dense_score": round(float(hit.get("score") or 0), 6),
        "id": payload.get("card_id"),
        "type": payload.get("card_type"),
        "title": payload.get("title"),
        "name": payload.get("name"),
        "article_uid": payload.get("article_uid"),
        "source_account": payload.get("source_account"),
        "text": str(payload.get("text") or "")[:500],
        "text_sha1": payload.get("text_sha1"),
        "collection_kind": collection_kind,
    }


def merge_candidates(results_by_kind: dict[str, list[dict[str, Any]]], limit: int) -> list[dict[str, Any]]:
    rows = []
    for kind, hits in results_by_kind.items():
        for hit in hits:
            rows.append(qdrant_hit_to_candidate(hit, kind))
    rows.sort(key=lambda item: float(item.get("dense_score") or 0), reverse=True)
    rows = rows[:limit]
    for rank, row in enumerate(rows, start=1):
        row["dense_rank"] = rank
    return rows


def summarize_kind_counts(hits: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(hit.get("type") or "unknown") for hit in hits))


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Qdrant Serving Retrieval Smoke",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- query_count: `{report['query_count']}`",
        f"- per_collection_limit: `{report['per_collection_limit']}`",
        f"- merged_limit: `{report['merged_limit']}`",
        f"- rerank_k: `{report['rerank_k']}`",
        f"- qdrant_sec: `{report['qdrant_sec']}`",
        f"- rerank_sec: `{report['rerank_sec']}`",
        f"- self_signature_policy_top5_rate: `{report['self_signature_policy_top5_rate']}`",
        f"- self_non_article_policy_top5_rate: `{report['self_non_article_policy_top5_rate']}`",
        f"- self_article_recall_rate: `{report['self_article_recall_rate']}`",
        "",
        "## Queries",
        "",
    ]
    for query in report["queries"]:
        lines.append(f"### {query['id']}: {query['query']}")
        lines.append(f"- source: `{query.get('source')}`")
        lines.append(f"- qdrant_elapsed_sec: `{query['qdrant_elapsed_sec']}`")
        lines.append(f"- expected_signature_policy_rank: `{query.get('expected_signature_policy_rank')}`")
        lines.append(f"- policy_kind_counts: `{query['policy_kind_counts']}`")
        lines.append("")
        lines.append("| policy_rank | rerank_score | rerank_rank | dense_rank | kind | label |")
        lines.append("|---:|---:|---:|---:|---|---|")
        for hit in query["policy_hits"]:
            label = card_label(hit).replace("|", "/")
            lines.append(
                f"| {hit['policy_rank']} | {hit.get('rerank_score')} | {hit.get('rerank_rank')} | "
                f"{hit.get('dense_rank')} | {hit.get('type', '')} | {label} |"
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    require_local_qdrant(args.qdrant_url)
    metadata = read_json(args.vector_dir / "metadata.json")
    model = str(metadata.get("model") or args.embedding_model)
    dim = int(metadata.get("dim") or args.dim)
    collections = {kind: collection_name(kind, model, dim, args.stamp) for kind in KINDS}
    health = {kind: collection_health(args.qdrant_url, name) for kind, name in collections.items()}
    if not all(item["healthy"] for item in health.values()):
        raise RuntimeError(f"unhealthy collections: {json.dumps(health, ensure_ascii=False)}")

    enforce_native_heavy_python_guard("evaluate_qdrant_serving_retrieval_smoke.run")
    import torch
    from sentence_transformers import CrossEncoder, SentenceTransformer

    type_targets = parse_type_targets(args.type_targets)
    queries = [dict(item) for item in FIXED_QUERIES] + select_self_queries(args.vector_dir / "card_texts.jsonl", args.self_query_count)
    query_texts = [str(item["query"]) for item in queries]

    all_started = time.perf_counter()
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
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    qdrant_started = time.perf_counter()
    dense_results = []
    for query, query_vector in zip(queries, np.asarray(query_vectors, dtype="float32")):
        started = time.perf_counter()
        results_by_kind = {}
        for kind, collection in collections.items():
            hits, _elapsed = qdrant_search(args.qdrant_url, collection, query_vector.tolist(), args.per_collection_limit)
            results_by_kind[kind] = hits
        dense_results.append((query, merge_candidates(results_by_kind, args.merged_limit), time.perf_counter() - started))
    qdrant_sec = time.perf_counter() - qdrant_started

    rerank_started = time.perf_counter()
    reranker = CrossEncoder(args.reranker_model, device=args.device)
    query_reports = []
    self_total = 0
    self_policy_top5 = 0
    self_non_article_total = 0
    self_non_article_policy_top5 = 0
    self_article_total = 0
    self_article_recalled = 0
    pair_count = 0
    for query, candidates, qdrant_elapsed in dense_results:
        rerank_query = format_rerank_query(str(query["query"]), args.instruction)
        pairs = [(rerank_query, str(candidate.get("text") or "")) for candidate in candidates]
        pair_count += len(pairs)
        scores = reranker.predict(pairs, batch_size=args.rerank_batch_size, show_progress_bar=False) if pairs else []
        ranked = rank_hits(candidates, [float(score) for score in scores])
        for hit in ranked:
            hit["dense_rank"] = int(hit.get("dense_rank") or 0)
        policy_hits = apply_policy(
            ranked,
            limit=args.policy_limit,
            max_per_signature=args.max_per_signature,
            max_per_article=args.max_per_article,
            type_targets=type_targets,
        )
        expected_card = query.get("expected_card")
        expected_rank = first_expected_rank(ranked, query.get("expected_card_id"))
        expected_signature_rank = first_expected_signature_rank(ranked, expected_card)
        expected_signature_policy_rank = None
        if expected_signature_rank is not None:
            expected_signature = hit_signature(expected_card)
            for hit in policy_hits:
                if hit_signature(hit) == expected_signature:
                    expected_signature_policy_rank = int(hit["policy_rank"])
                    break
        if query.get("source") == "self_alignment":
            self_total += 1
            expected_kind = str((expected_card or {}).get("type") or "")
            if expected_kind == "article":
                self_article_total += 1
                if expected_signature_rank is not None:
                    self_article_recalled += 1
            else:
                self_non_article_total += 1
                if expected_signature_policy_rank is not None and expected_signature_policy_rank <= 5:
                    self_non_article_policy_top5 += 1
            if expected_signature_policy_rank is not None and expected_signature_policy_rank <= 5:
                self_policy_top5 += 1
        query_reports.append(
            {
                "id": query.get("id"),
                "query": query.get("query"),
                "source": query.get("source"),
                "qdrant_elapsed_sec": round(qdrant_elapsed, 6),
                "dense_kind_counts": summarize_kind_counts(ranked[: args.policy_limit]),
                "policy_kind_counts": summarize_kind_counts(policy_hits),
                "expected_card_id": query.get("expected_card_id"),
                "expected_rerank_rank": expected_rank,
                "expected_signature_rank": expected_signature_rank,
                "expected_signature_policy_rank": expected_signature_policy_rank,
                "reranked_hits": ranked[: args.rerank_k],
                "policy_hits": policy_hits,
            }
        )
    rerank_sec = time.perf_counter() - rerank_started
    vram_peak_gb = None
    if torch.cuda.is_available():
        vram_peak_gb = round(torch.cuda.max_memory_allocated() / (1024**3), 3)

    report = {
        "schema_version": "stage7_qdrant_serving_retrieval_smoke.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "execution_host_policy": "local RTX 4090; report-only; no Qdrant writes, no alias promote, no D: scans",
        "ok": all(item["healthy"] for item in health.values())
        and (self_non_article_total == 0 or self_non_article_policy_top5 == self_non_article_total)
        and (self_article_total == 0 or self_article_recalled == self_article_total),
        "vector_dir": str(args.vector_dir),
        "qdrant_url": args.qdrant_url,
        "collections": collections,
        "collection_health": health,
        "embedding_model": args.embedding_model,
        "reranker_model": args.reranker_model,
        "query_count": len(query_reports),
        "pair_count": pair_count,
        "per_collection_limit": args.per_collection_limit,
        "merged_limit": args.merged_limit,
        "rerank_k": args.rerank_k,
        "policy_limit": args.policy_limit,
        "type_targets": type_targets,
        "embed_sec": round(embed_sec, 3),
        "qdrant_sec": round(qdrant_sec, 3),
        "rerank_sec": round(rerank_sec, 3),
        "total_sec": round(time.perf_counter() - all_started, 3),
        "vram_peak_gb": vram_peak_gb,
        "self_signature_policy_top5_rate": round(self_policy_top5 / max(self_total, 1), 4),
        "self_non_article_policy_top5_rate": round(
            self_non_article_policy_top5 / max(self_non_article_total, 1),
            4,
        ),
        "self_article_recall_rate": round(self_article_recalled / max(self_article_total, 1), 4),
        "queries": query_reports,
    }
    write_json(args.out_dir / "qdrant_serving_retrieval_smoke.json", report)
    write_markdown(args.out_dir / "qdrant_serving_retrieval_smoke.md", report)
    print(json.dumps({"ok": report["ok"], "json": str(args.out_dir / "qdrant_serving_retrieval_smoke.json"), "markdown": str(args.out_dir / "qdrant_serving_retrieval_smoke.md")}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vector-dir", type=Path, default=DEFAULT_VECTOR_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--stamp", default="20260514")
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--dim", type=int, default=1024)
    parser.add_argument("--truncate-dim", type=int, default=1024)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--embedding-batch-size", type=int, default=8)
    parser.add_argument("--rerank-batch-size", type=int, default=8)
    parser.add_argument("--self-query-count", type=int, default=3)
    parser.add_argument("--per-collection-limit", type=int, default=200)
    parser.add_argument("--merged-limit", type=int, default=200)
    parser.add_argument("--rerank-k", type=int, default=10)
    parser.add_argument("--policy-limit", type=int, default=10)
    parser.add_argument("--max-per-signature", type=int, default=1)
    parser.add_argument("--max-per-article", type=int, default=2)
    parser.add_argument("--type-targets", default=DEFAULT_TYPE_TARGETS)
    parser.add_argument("--instruction", default=DEFAULT_INSTRUCTION)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not (args.vector_dir / "metadata.json").exists():
        raise SystemExit(f"metadata not found under {args.vector_dir}")
    if not (args.vector_dir / "card_texts.jsonl").exists():
        raise SystemExit(f"card_texts not found under {args.vector_dir}")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
