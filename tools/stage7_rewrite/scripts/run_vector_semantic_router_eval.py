#!/usr/bin/env python3
"""Run a bounded semantic router eval for current/control and canary vectors.

The eval embeds a small hard-query set through the channel-appropriate query
encoder, queries local Qdrant collections, applies language routing plus RRF,
and writes a report. It does not write Qdrant, promote aliases, touch Neo4j,
SQLite, mem0, paid APIs, production publish, or scan D:.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_vector_router_smoke import classify_query_language, require_local_url, rrf_fuse, route_channels
from stage7_runtime_guard import enforce_native_heavy_python_guard


DEFAULT_OUT_DIR = Path("reports/vector_semantic_router_eval_20260518")
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
DEFAULT_QWEN_ENDPOINT = "http://127.0.0.1:11441"
QWEN_MODEL = "Qwen/Qwen3-Embedding-4B"
SNOWFLAKE_MODEL = "Snowflake/snowflake-arctic-embed-l-v2.0"
ENGLISH_MODEL = "BAAI/bge-large-en-v1.5"
SNOWFLAKE_LOCAL_DIR = Path(r"D:\AI\models\embeddings\Snowflake--snowflake-arctic-embed-l-v2.0")
ENGLISH_LOCAL_DIR = Path(r"D:\AI\models\embeddings\BAAI--bge-large-en-v1.5")
COLLECTIONS = {
    "qwen3_current": "wechat_stage7_article_qwen3_embedding_4b_1024_current",
    "snowflake_canary": "wechat_stage7_article_snowflake_snowflake_arctic_embed_l_v2_0_1024_20260518_snowflake_canary_staging",
    "english_sidecar": "wechat_stage7_article_baai_bge_large_en_v1_5_1024_20260518_english_sidecar_staging",
}
HARD_QUERIES = [
    {"id": "zh_shanghai_club", "query": "上海 电子音乐 俱乐部 活动 阵容"},
    {"id": "zh_beijing_dada", "query": "北京 Dada 酒吧 DJ 活动"},
    {"id": "en_profile", "query": "DJ SoundCloud Bandcamp profile"},
    {"id": "mixed_oil_lineup", "query": "深圳 OIL CLUB 周末 lineup"},
    {"id": "mixed_heim_party", "query": "Heim Shanghai 周五 party"},
]
SCHEMA_VERSION = "stage7_vector_semantic_router_eval.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_root(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"} or raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses broad D root: {path}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def qdrant_search(qdrant_url: str, collection: str, vector: list[float], limit: int) -> list[dict[str, Any]]:
    response = requests.post(
        f"{qdrant_url.rstrip('/')}/collections/{quote(collection)}/points/search",
        json={"vector": vector, "limit": limit, "with_payload": True},
        timeout=60,
    )
    if response.status_code == 404:
        response = requests.post(
            f"{qdrant_url.rstrip('/')}/collections/{quote(collection)}/points/query",
            json={"query": vector, "limit": limit, "with_payload": True},
            timeout=60,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Qdrant search failed {response.status_code}: {response.text[:500]}")
    result = response.json().get("result")
    if isinstance(result, dict):
        result = result.get("points")
    return result or []


def normalize_hit(channel: str, collection: str, rank: int, hit: dict[str, Any]) -> dict[str, Any]:
    payload = hit.get("payload") or {}
    parent_id = (
        payload.get("parent_id")
        or payload.get("article_uid")
        or payload.get("card_id")
        or payload.get("object_id")
        or payload.get("job_id")
        or hit.get("id")
    )
    return {
        "channel": channel,
        "collection": collection,
        "rank": rank,
        "score": hit.get("score"),
        "parent_id": str(parent_id or ""),
        "card_id": payload.get("card_id"),
        "job_id": payload.get("job_id"),
        "text_sha1": payload.get("text_sha1"),
        "field_path": payload.get("field_path"),
        "model": payload.get("model"),
        "label": compact_label(payload),
    }


def compact_label(payload: dict[str, Any]) -> str:
    label = payload.get("title") or payload.get("name") or payload.get("text") or ""
    return re.sub(r"\s+", " ", str(label).strip())[:180]


def embed_qwen(endpoint: str, queries: list[str], timeout: int) -> list[list[float]]:
    require_local_url(endpoint, "Qwen embedding endpoint")
    response = requests.post(
        f"{endpoint.rstrip('/')}/v1/embeddings",
        json={"model": QWEN_MODEL, "input": queries},
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Qwen endpoint failed {response.status_code}: {response.text[:500]}")
    rows = response.json().get("data") or []
    vectors = [row.get("embedding") for row in rows]
    if len(vectors) != len(queries):
        raise RuntimeError(f"Qwen embedding count mismatch: {len(vectors)} != {len(queries)}")
    return [[float(value) for value in vector] for vector in vectors]


def format_query(model_role: str, text: str) -> str:
    if model_role == "snowflake_canary":
        return "query: " + text
    return text


def embed_local(model_name: str, local_dir: Path, queries: list[str], *, batch_size: int, device: str) -> list[list[float]]:
    reject_d_root(local_dir, "local_model_dir")
    enforce_native_heavy_python_guard(f"run_vector_semantic_router_eval.embed_local:{model_name}")
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(
        str(local_dir),
        device=device,
        trust_remote_code=True,
        local_files_only=True,
    )
    vectors = model.encode(
        queries,
        batch_size=max(1, batch_size),
        normalize_embeddings=True,
        truncate_dim=1024,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return [[float(value) for value in row] for row in vectors.tolist()]


def embed_queries(args: argparse.Namespace, queries: list[dict[str, Any]]) -> dict[str, list[list[float]]]:
    texts = [item["query"] for item in queries]
    started = time.perf_counter()
    qwen_vectors = embed_qwen(args.qwen_endpoint, texts, args.timeout_sec)
    qwen_sec = time.perf_counter() - started

    started = time.perf_counter()
    snowflake_vectors = embed_local(
        SNOWFLAKE_MODEL,
        args.snowflake_local_dir,
        [format_query("snowflake_canary", text) for text in texts],
        batch_size=args.batch_size,
        device=args.device,
    )
    snowflake_sec = time.perf_counter() - started

    started = time.perf_counter()
    english_vectors = embed_local(
        ENGLISH_MODEL,
        args.english_local_dir,
        [format_query("english_sidecar", text) for text in texts],
        batch_size=args.batch_size,
        device=args.device,
    )
    english_sec = time.perf_counter() - started
    return {
        "qwen3_current": qwen_vectors,
        "snowflake_canary": snowflake_vectors,
        "english_sidecar": english_vectors,
        "_timing": {
            "qwen_endpoint_sec": round(qwen_sec, 3),
            "snowflake_local_sec": round(snowflake_sec, 3),
            "english_local_sec": round(english_sec, 3),
        },
    }


def run_eval(args: argparse.Namespace) -> dict[str, Any]:
    require_local_url(args.qdrant_url, "Qdrant URL")
    queries = [dict(item) for item in HARD_QUERIES]
    vectors_by_channel = embed_queries(args, queries)
    timings = vectors_by_channel.pop("_timing")
    query_reports = []
    for index, query in enumerate(queries):
        lang = classify_query_language(query["query"])
        channels = route_channels(lang)
        channel_hits: dict[str, list[dict[str, Any]]] = {}
        for channel in channels:
            collection = COLLECTIONS[channel]
            hits = qdrant_search(args.qdrant_url, collection, vectors_by_channel[channel][index], args.top_k)
            channel_hits[channel] = [
                normalize_hit(channel, collection, rank, hit) for rank, hit in enumerate(hits, start=1)
            ]
        fused = rrf_fuse(channel_hits, limit=args.fused_limit)
        query_reports.append(
            {
                **query,
                "lang": lang,
                "routed_channels": channels,
                "channel_hit_counts": {channel: len(hits) for channel, hits in channel_hits.items()},
                "top_by_channel": {channel: hits[:3] for channel, hits in channel_hits.items()},
                "fused": fused,
            }
        )
    no_empty_routes = all(all(count > 0 for count in report["channel_hit_counts"].values()) for report in query_reports)
    zh_has_no_english = all(
        "english_sidecar" not in report["routed_channels"] for report in query_reports if report["lang"] == "zh"
    )
    en_has_english = all(
        "english_sidecar" in report["routed_channels"] for report in query_reports if report["lang"] == "en"
    )
    mixed_has_all = all(
        set(report["routed_channels"]) == {"qwen3_current", "snowflake_canary", "english_sidecar"}
        for report in query_reports
        if report["lang"] == "mixed"
    )
    ok = no_empty_routes and zh_has_no_english and en_has_english and mixed_has_all
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": ok,
        "decision": "vector_semantic_router_eval_ready" if ok else "vector_semantic_router_eval_needs_review",
        "qdrant_url": args.qdrant_url,
        "qwen_endpoint": args.qwen_endpoint,
        "collections": COLLECTIONS,
        "query_count": len(query_reports),
        "top_k": args.top_k,
        "fused_limit": args.fused_limit,
        "timings": timings,
        "gates": {
            "no_empty_routes": no_empty_routes,
            "zh_has_no_english_sidecar": zh_has_no_english,
            "en_has_english_sidecar": en_has_english,
            "mixed_has_all_channels": mixed_has_all,
        },
        "queries": query_reports,
        "scope_note": "Semantic eval is bounded to article current plus 1000-row Snowflake/English canary collections; it is not a full sidecar quality verdict.",
        "safety": {
            "query_embedding_executed": True,
            "qdrant_write_executed": False,
            "qdrant_alias_change_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "production_publish_executed": False,
            "d_scan_executed": False,
        },
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Vector Semantic Router Eval",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- ok: `{report['ok']}`",
        f"- query_count: `{report['query_count']}`",
        f"- timings: `{report['timings']}`",
        "",
        "## Gates",
        "",
    ]
    for key, value in report["gates"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Queries", ""])
    for query in report["queries"]:
        lines.append(f"- `{query['id']}` lang `{query['lang']}` channels `{query['routed_channels']}` hits `{query['channel_hit_counts']}` fused `{len(query['fused'])}`")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(report["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--qwen-endpoint", default=DEFAULT_QWEN_ENDPOINT)
    parser.add_argument("--snowflake-local-dir", type=Path, default=SNOWFLAKE_LOCAL_DIR)
    parser.add_argument("--english-local-dir", type=Path, default=ENGLISH_LOCAL_DIR)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--fused-limit", type=int, default=8)
    parser.add_argument("--timeout-sec", type=int, default=120)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    report = run_eval(args)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "vector_semantic_router_eval.json", report)
    write_markdown(args.out_dir / "vector_semantic_router_eval.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "report": str(args.out_dir / "vector_semantic_router_eval.json"),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["ok"] else 2


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
