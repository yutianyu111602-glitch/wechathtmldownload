"""Measure Qdrant full-staging retrieval latency before indexing decisions.

This is report-only. It reads the local vector artifact and Qdrant full-staging
collections, then runs dense top-K searches using existing card vectors as
queries. It does not write points, update collection configs, promote aliases,
start Neo4j, touch production SQLite, use paid APIs, or scan D:.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import numpy as np
import requests


DEFAULT_VECTOR_DIR = Path("reports/vector_full_qwen3_4b_1024_20260514")
DEFAULT_OUT_DIR = Path("reports/qdrant_full_qwen3_4b_1024_20260514")
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
KINDS = ("article", "entity", "event")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


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


def text_sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def iter_card_rows(card_texts_path: Path):
    with card_texts_path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle):
            stripped = line.strip()
            if stripped:
                row = json.loads(stripped)
                row["_vector_index"] = idx
                yield row


def select_rows(card_texts_path: Path, per_kind: int) -> dict[str, list[dict[str, Any]]]:
    selected: dict[str, list[dict[str, Any]]] = {kind: [] for kind in KINDS}
    for row in iter_card_rows(card_texts_path):
        kind = str(row.get("type") or "")
        if kind in selected and len(selected[kind]) < per_kind:
            selected[kind].append(row)
        if all(len(rows) >= per_kind for rows in selected.values()):
            break
    return selected


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    idx = min(len(values) - 1, max(0, round((len(values) - 1) * pct)))
    return round(values[idx], 6)


def summarize_latency(values: list[float]) -> dict[str, float | None]:
    return {
        "count": len(values),
        "min_sec": round(min(values), 6) if values else None,
        "p50_sec": percentile(values, 0.50),
        "p95_sec": percentile(values, 0.95),
        "max_sec": round(max(values), 6) if values else None,
        "avg_sec": round(statistics.mean(values), 6) if values else None,
    }


def search_collection(
    qdrant_url: str,
    collection: str,
    vector: list[float],
    limit: int,
) -> tuple[list[dict[str, Any]], float]:
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
    hits = result or []
    for hit in hits:
        hit["collection"] = collection
    return hits, elapsed


def merge_hits(results_by_kind: dict[str, list[dict[str, Any]]], limit: int) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for kind, rows in results_by_kind.items():
        for row in rows:
            item = dict(row)
            item["collection_kind"] = kind
            hits.append(item)
    hits.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
    return hits[:limit]


def find_rank(hits: list[dict[str, Any]], expected_card_id: str, expected_text_sha1: str, expected_type: str) -> dict[str, int | None]:
    exact_rank = None
    equivalent_rank = None
    for idx, hit in enumerate(hits, start=1):
        payload = hit.get("payload") or {}
        if exact_rank is None and payload.get("card_id") == expected_card_id:
            exact_rank = idx
        if equivalent_rank is None and payload.get("card_type") == expected_type and payload.get("text_sha1") == expected_text_sha1:
            equivalent_rank = idx
        if exact_rank is not None and equivalent_rank is not None:
            break
    return {"exact_rank": exact_rank, "equivalent_rank": equivalent_rank}


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


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Qdrant Full Staging Latency Smoke",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- query_count: `{report['query_count']}`",
        f"- per_collection_limit: `{report['per_collection_limit']}`",
        f"- merged_limit: `{report['merged_limit']}`",
        f"- exact_top200_rate: `{report['exact_topk_rate']}`",
        f"- equivalent_top200_rate: `{report['equivalent_topk_rate']}`",
        f"- merged_latency: `{report['merged_latency']}`",
        "",
        "## Collection Health",
        "",
        "| Kind | Collection | Status | Optimizer | Points | Indexed |",
        "|---|---|---|---|---:|---:|",
    ]
    for kind, name in report["collections"].items():
        health = report["collection_health"][kind]
        lines.append(
            f"| `{kind}` | `{name}` | `{health['status']}` | `{health['optimizer_status']}` | {health['points_count']} | {health['indexed_vectors_count']} |"
        )
    lines.extend(["", "## Queries", ""])
    for item in report["queries"]:
        lines.append(
            f"- `{item['expected_kind']}` `{item['expected_card_id']}` merged_sec={item['merged_elapsed_sec']} exact_rank={item['exact_rank']} equivalent_rank={item['equivalent_rank']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    require_local_qdrant(args.qdrant_url)
    metadata = read_json(args.vector_dir / "metadata.json")
    model = str(metadata.get("model") or args.model)
    dim = int(metadata.get("dim") or args.dim)
    collections = {kind: collection_name(kind, model, dim, args.stamp) for kind in KINDS}
    collection_health_map = {kind: collection_health(args.qdrant_url, name) for kind, name in collections.items()}
    if not all(item["healthy"] for item in collection_health_map.values()):
        raise RuntimeError(f"unhealthy collections: {json.dumps(collection_health_map, ensure_ascii=False)}")

    selected = select_rows(args.vector_dir / "card_texts.jsonl", args.per_kind)
    vectors = np.load(args.vector_dir / "vectors.npy", mmap_mode="r")
    queries = []
    merged_latencies = []
    collection_latencies: dict[str, list[float]] = {kind: [] for kind in KINDS}
    exact_hits = 0
    equivalent_hits = 0
    total = 0

    for kind, rows in selected.items():
        for row in rows:
            total += 1
            vector = np.asarray(vectors[int(row["_vector_index"])], dtype="float32").tolist()
            started = time.perf_counter()
            results_by_kind = {}
            per_collection_elapsed = {}
            for collection_kind, collection in collections.items():
                hits, elapsed = search_collection(args.qdrant_url, collection, vector, args.per_collection_limit)
                results_by_kind[collection_kind] = hits
                per_collection_elapsed[collection_kind] = round(elapsed, 6)
                collection_latencies[collection_kind].append(elapsed)
            merged = merge_hits(results_by_kind, args.merged_limit)
            merged_elapsed = time.perf_counter() - started
            merged_latencies.append(merged_elapsed)
            expected_hash = text_sha1(str(row.get("text") or ""))
            ranks = find_rank(merged, str(row.get("id")), expected_hash, kind)
            exact_hits += int(ranks["exact_rank"] is not None)
            equivalent_hits += int(ranks["equivalent_rank"] is not None)
            queries.append(
                {
                    "expected_kind": kind,
                    "expected_card_id": row.get("id"),
                    "expected_text_sha1": expected_hash,
                    "merged_elapsed_sec": round(merged_elapsed, 6),
                    "per_collection_elapsed_sec": per_collection_elapsed,
                    "exact_rank": ranks["exact_rank"],
                    "equivalent_rank": ranks["equivalent_rank"],
                    "top1_card_id": ((merged[0].get("payload") or {}).get("card_id") if merged else None),
                    "top1_score": (merged[0].get("score") if merged else None),
                }
            )

    report = {
        "schema_version": "stage7_qdrant_full_staging_latency_smoke.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "execution_host_policy": "local report-only; no model load, no Qdrant writes, no alias promote, no D: scans",
        "ok": equivalent_hits == total and all(item["healthy"] for item in collection_health_map.values()),
        "vector_dir": str(args.vector_dir),
        "qdrant_url": args.qdrant_url,
        "collections": collections,
        "collection_health": collection_health_map,
        "query_count": total,
        "per_kind": args.per_kind,
        "per_collection_limit": args.per_collection_limit,
        "merged_limit": args.merged_limit,
        "exact_topk_rate": round(exact_hits / max(total, 1), 4),
        "equivalent_topk_rate": round(equivalent_hits / max(total, 1), 4),
        "merged_latency": summarize_latency(merged_latencies),
        "collection_latency": {kind: summarize_latency(values) for kind, values in collection_latencies.items()},
        "queries": queries,
    }
    write_json(args.out_dir / "qdrant_full_staging_latency_smoke.json", report)
    write_markdown(args.out_dir / "qdrant_full_staging_latency_smoke.md", report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ok"] else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vector-dir", type=Path, default=DEFAULT_VECTOR_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--stamp", default="20260514")
    parser.add_argument("--model", default="Qwen/Qwen3-Embedding-4B")
    parser.add_argument("--dim", type=int, default=1024)
    parser.add_argument("--per-kind", type=int, default=2)
    parser.add_argument("--per-collection-limit", type=int, default=200)
    parser.add_argument("--merged-limit", type=int, default=200)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not (args.vector_dir / "metadata.json").exists():
        raise SystemExit(f"metadata not found under {args.vector_dir}")
    if not (args.vector_dir / "card_texts.jsonl").exists():
        raise SystemExit(f"card_texts not found under {args.vector_dir}")
    if not (args.vector_dir / "vectors.npy").exists():
        raise SystemExit(f"vectors.npy not found under {args.vector_dir}")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
