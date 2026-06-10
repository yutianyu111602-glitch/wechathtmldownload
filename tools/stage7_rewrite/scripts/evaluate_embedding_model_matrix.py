"""Evaluate embedding models for the underground electronic music map.

Reads existing Stage7/vector/poster artifacts, builds a bounded multi-quality
retrieval benchmark, and writes JSON/Markdown reports. No Qdrant, Neo4j, or
production DB writes.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from stage7_runtime_guard import enforce_native_heavy_python_guard


DEFAULT_MODELS = [
    {
        "repo_id": "BAAI/bge-m3",
        "local_dir": r"D:\AI\models\embeddings\BAAI--bge-m3",
        "dim_expected": 1024,
        "family": "bge",
        "query_prefix": "",
    },
    {
        "repo_id": "jinaai/jina-embeddings-v5-text-small",
        "local_dir": r"D:\AI\models\embeddings\jinaai--jina-embeddings-v5-text-small",
        "dim_expected": 1024,
        "family": "jina",
        "query_prefix": "",
        "encode_kwargs_doc": {"task": "retrieval"},
        "encode_kwargs_query": {"task": "retrieval"},
    },
    {
        "repo_id": "Qwen/Qwen3-Embedding-0.6B",
        "local_dir": r"D:\AI\models\embeddings\Qwen--Qwen3-Embedding-0.6B",
        "dim_expected": 1024,
        "family": "qwen3",
        "query_prefix": "",
    },
    {
        "repo_id": "Snowflake/snowflake-arctic-embed-l-v2.0",
        "local_dir": r"D:\AI\models\embeddings\Snowflake--snowflake-arctic-embed-l-v2.0",
        "dim_expected": 1024,
        "family": "snowflake",
        "query_prefix": "query: ",
    },
    {
        "repo_id": "jinaai/jina-embeddings-v3",
        "local_dir": r"D:\AI\models\embeddings\jinaai--jina-embeddings-v3",
        "dim_expected": 1024,
        "family": "jina",
        "query_prefix": "",
        "encode_kwargs_doc": {"task": "retrieval.passage"},
        "encode_kwargs_query": {"task": "retrieval.query"},
    },
    {
        "repo_id": "intfloat/multilingual-e5-large-instruct",
        "local_dir": r"D:\AI\models\embeddings\intfloat--multilingual-e5-large-instruct",
        "dim_expected": 1024,
        "family": "e5",
        "query_prefix": "Instruct: Given a web article or event card from China's underground electronic music scene, retrieve the matching document.\nQuery: ",
    },
    {
        "repo_id": "BAAI/bge-large-en-v1.5",
        "local_dir": r"D:\AI\models\embeddings\BAAI--bge-large-en-v1.5",
        "dim_expected": 1024,
        "family": "bge-en",
        "query_prefix": "",
    },
]


FIXED_DOMAIN_QUERIES = [
    ("fixed_venue_shanghai", "上海 电子音乐 俱乐部 活动 阵容", ["article", "event", "entity"]),
    ("fixed_beijing_dada", "北京 Dada 酒吧 DJ 活动", ["article", "event", "entity"]),
    ("fixed_shenzhen_oil", "深圳 OIL CLUB 电子音乐 活动", ["article", "event", "entity", "poster"]),
    ("fixed_hakka_wine", "院吧 Hakka Bar 葡萄酒 酒单", ["article", "entity"]),
    ("fixed_lineup_weekend", "本周末 派对 lineup 阵容 场地", ["article", "event", "poster"]),
    ("fixed_social_links", "DJ SoundCloud Bandcamp Linktree profile", ["article", "entity"]),
]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_jsonl(path: Path, limit: int | None = None):
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit is not None and i >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def compact_text(value: Any, max_chars: int = 900) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def cjk_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def latin_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z]", text))


def classify_language(text: str) -> str:
    cjk = cjk_count(text)
    latin = latin_count(text)
    if cjk and latin:
        return "mixed"
    if cjk:
        return "zh"
    if latin:
        return "en"
    return "unknown"


def add_doc(
    docs: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    *,
    doc_id: str,
    text: str,
    source: str,
    quality: str,
    doc_type: str,
    query: str,
) -> None:
    text = compact_text(text, 1200)
    query = compact_text(query, 500)
    if len(text) < 6 or len(query) < 2:
        return
    doc_language = classify_language(text)
    query_language = classify_language(query)
    docs.append(
        {
            "id": doc_id,
            "text": text,
            "source": source,
            "quality": quality,
            "type": doc_type,
            "language": doc_language,
        }
    )
    queries.append(
        {
            "id": f"q_{doc_id}",
            "query": query,
            "expected_doc_id": doc_id,
            "source": source,
            "quality": quality,
            "type": doc_type,
            "language": query_language,
            "doc_language": doc_language,
        }
    )


def stable_quality(row: dict[str, Any]) -> str:
    metrics = (((row.get("quality") or {}).get("scorer_v2") or {}).get("metrics") or {})
    routing = (((row.get("quality") or {}).get("scorer_v2") or {}).get("routing") or {})
    decision = routing.get("decision") or ""
    if decision == "accept_flash" and metrics.get("schema_ok", True) and metrics.get("evidence_hit_rate", 1) >= 0.98:
        return "stable_high"
    if "repair" in decision or not metrics.get("schema_ok", True):
        return "stable_repaired"
    if metrics.get("output_count", 1) <= 1 or metrics.get("input_chars", 0) < 900:
        return "stable_sparse"
    return "stable_mixed"


def build_from_stable_articles(root: Path, docs: list[dict[str, Any]], queries: list[dict[str, Any]], limit: int) -> int:
    path = root / "reports/fullmap_47k_ready_text_authok_20260513_174006/stable_extract_v1/stable_articles.jsonl"
    if not path.exists():
        return 0
    added = 0
    buckets: dict[str, int] = defaultdict(int)
    for row in iter_jsonl(path):
        q = stable_quality(row)
        if buckets[q] >= max(20, limit // 4):
            continue
        uid = row.get("article_uid") or row.get("article_id") or f"stable_{added}"
        title = row.get("title") or ""
        account = row.get("source_account") or ""
        add_doc(
            docs,
            queries,
            doc_id=f"stable_article_{added:05d}",
            text=f"文章 | 公众号:{account} | 标题:{title} | 主题:{' '.join(row.get('topics') or [])}",
            source="stable_extract_v1",
            quality=q,
            doc_type="article",
            query=f"{account} {title}",
        )
        added += 1
        buckets[q] += 1
        for entity in (row.get("entities") or [])[:4]:
            name = entity.get("name") or ""
            etype = entity.get("type") or entity.get("entity_type") or ""
            bio = entity.get("bio") or ""
            add_doc(
                docs,
                queries,
                doc_id=f"stable_entity_{added:05d}",
                text=f"实体 | 名称:{name} | 类型:{etype} | 来源公众号:{account} | 标题:{title} | 简介:{bio}",
                source="stable_extract_v1",
                quality=q,
                doc_type="entity",
                query=f"{name} {etype} {account}",
            )
            added += 1
        for event in (row.get("events") or [])[:3]:
            name = event.get("name") or title
            place = event.get("place") or ""
            time_text = event.get("time") or ""
            participants = " ".join(event.get("participants") or [])
            add_doc(
                docs,
                queries,
                doc_id=f"stable_event_{added:05d}",
                text=f"活动 | 名称:{name} | 时间:{time_text} | 场地:{place} | 阵容:{participants} | 公众号:{account} | 标题:{title}",
                source="stable_extract_v1",
                quality=q,
                doc_type="event",
                query=f"{name} {place} {participants}",
            )
            added += 1
        if added >= limit:
            break
    return added


def build_from_existing_card_texts(root: Path, docs: list[dict[str, Any]], queries: list[dict[str, Any]], limit: int) -> int:
    path = root / "reports/vectors_bge_m3_20260510/card_texts.jsonl"
    if not path.exists():
        return 0
    added = 0
    for row in iter_jsonl(path, limit=limit):
        text = row.get("text") or ""
        name = row.get("name") or row.get("title") or row.get("account") or text
        dtype = row.get("type") or "card"
        version = row.get("version") or "legacy"
        add_doc(
            docs,
            queries,
            doc_id=f"legacy_bge_{added:05d}",
            text=f"{text} | version:{version}",
            source="vectors_bge_m3_20260510",
            quality="legacy_mixed",
            doc_type=dtype,
            query=f"{name} {row.get('account') or ''} {row.get('entity_type') or ''}",
        )
        added += 1
    return added


def build_from_ocr_entities(root: Path, docs: list[dict[str, Any]], queries: list[dict[str, Any]], limit: int) -> int:
    path = root / "reports/dajiala_paid_wave01_04_verified_ocr_entity_extraction_20260516/ocr_entities.jsonl"
    if not path.exists():
        return 0
    added = 0
    for row in iter_jsonl(path, limit=limit):
        name = row.get("entity_name") or ""
        etype = row.get("entity_type") or ""
        account = row.get("source_account") or ""
        evidence = row.get("evidence_text") or ""
        add_doc(
            docs,
            queries,
            doc_id=f"ocr_entity_{added:05d}",
            text=f"海报OCR实体 | 名称:{name} | 类型:{etype} | 公众号:{account} | 证据:{evidence}",
            source="ocr_entity_extraction",
            quality="ocr_noisy",
            doc_type="ocr_entity",
            query=f"{name} {etype} {account}",
        )
        added += 1
    return added


def build_from_paid_sidecars(root: Path, docs: list[dict[str, Any]], queries: list[dict[str, Any]], limit: int) -> int:
    base = root / "reports/dajiala_paid_wave05_process_20260517"
    if not base.exists():
        return 0
    added = 0
    for sidecar in base.glob("*/*/sidecar.json"):
        if added >= limit:
            break
        try:
            row = read_json(sidecar)
        except Exception:
            continue
        meta = row.get("meta") or {}
        footer = row.get("footer_info") or {}
        title = meta.get("title") or row.get("archive", {}).get("title") or ""
        account = meta.get("account_name") or sidecar.parent.parent.name
        lineup = " ".join(footer.get("lineup_lines") or [])
        address = " ".join(footer.get("venue_address_lines") or [])
        venue = footer.get("venue_name_candidate") or ""
        text = f"付费归档文章 | 公众号:{account} | 标题:{title} | 场地:{venue} | 地址:{address} | 阵容:{lineup} | 正文:{row.get('main_content') or ''}"
        add_doc(
            docs,
            queries,
            doc_id=f"paid_sidecar_{added:05d}",
            text=text,
            source="dajiala_paid_wave05_process",
            quality="paid_archive_reconstructed",
            doc_type="poster_article",
            query=f"{account} {title} {venue} {lineup} {address}",
        )
        added += 1
    return added


def add_fixed_queries(docs: list[dict[str, Any]], queries: list[dict[str, Any]]) -> None:
    by_type: dict[str, list[str]] = defaultdict(list)
    for doc in docs:
        by_type[doc["type"]].append(doc["id"])
    all_ids = [doc["id"] for doc in docs]
    for qid, text, preferred_types in FIXED_DOMAIN_QUERIES:
        candidates: list[str] = []
        for t in preferred_types:
            candidates.extend(by_type.get(t, []))
        if not candidates:
            candidates = all_ids
        queries.append(
            {
                "id": qid,
                "query": text,
                "expected_doc_id": candidates[0] if candidates else "",
                "expected_any_doc_ids": candidates[:50],
                "source": "fixed_domain",
                "quality": "domain_probe",
                "type": "fixed",
            }
        )


def build_dataset(root: Path, args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []
    counts = {
        "stable": build_from_stable_articles(root, docs, queries, args.stable_limit),
        "legacy": build_from_existing_card_texts(root, docs, queries, args.legacy_limit),
        "ocr": build_from_ocr_entities(root, docs, queries, args.ocr_limit),
        "paid_sidecar": build_from_paid_sidecars(root, docs, queries, args.sidecar_limit),
    }
    add_fixed_queries(docs, queries)
    return docs, queries, counts


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.clip(norms, 1e-12, None)


def format_for_model(texts: list[str], model_cfg: dict[str, Any], *, is_query: bool) -> list[str]:
    if is_query and model_cfg.get("query_prefix"):
        return [model_cfg["query_prefix"] + text for text in texts]
    family = model_cfg.get("family")
    if family == "e5" and not is_query:
        return ["passage: " + text for text in texts]
    if family == "snowflake" and not is_query:
        return ["passage: " + text for text in texts]
    return texts


def encode_texts(
    model: Any,
    texts: list[str],
    batch_size: int,
    normalize: bool,
    encode_kwargs: dict[str, Any] | None = None,
) -> np.ndarray:
    extra = encode_kwargs or {}
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=normalize,
        convert_to_numpy=True,
        show_progress_bar=False,
        **extra,
    )
    return vectors.astype("float32")


def score_model(
    model_cfg: dict[str, Any],
    docs: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    enforce_native_heavy_python_guard(f"evaluate_embedding_model_matrix.score_model:{model_cfg.get('repo_id')}")
    from sentence_transformers import SentenceTransformer

    import torch

    local_dir = Path(model_cfg["local_dir"])
    result: dict[str, Any] = {
        "repo_id": model_cfg["repo_id"],
        "local_dir": str(local_dir),
        "expected_dim": model_cfg["dim_expected"],
        "family": model_cfg.get("family"),
        "status": "pending",
    }
    if not local_dir.exists():
        result.update({"status": "missing", "error": "local_dir does not exist"})
        return result

    started = time.time()
    try:
        load_started = time.time()
        network_code_fallback = False
        try:
            model = SentenceTransformer(
                str(local_dir),
                device=args.device,
                trust_remote_code=True,
                local_files_only=True,
            )
        except Exception:
            if not args.allow_network_code:
                raise
            network_code_fallback = True
            model = SentenceTransformer(
                str(local_dir),
                device=args.device,
                trust_remote_code=True,
                local_files_only=False,
            )
        if args.max_seq_length:
            model.max_seq_length = args.max_seq_length
        load_sec = time.time() - load_started

        doc_texts = format_for_model([d["text"] for d in docs], model_cfg, is_query=False)
        query_texts = format_for_model([q["query"] for q in queries], model_cfg, is_query=True)
        encode_started = time.time()
        doc_encode_kwargs = model_cfg.get("encode_kwargs_doc") or model_cfg.get("encode_kwargs") or {}
        query_encode_kwargs = model_cfg.get("encode_kwargs_query") or model_cfg.get("encode_kwargs") or {}
        doc_vecs = encode_texts(model, doc_texts, args.batch_size, normalize=True, encode_kwargs=doc_encode_kwargs)
        query_vecs = encode_texts(model, query_texts, args.batch_size, normalize=True, encode_kwargs=query_encode_kwargs)
        encode_sec = time.time() - encode_started
        if not args.assume_normalized:
            doc_vecs = l2_normalize(doc_vecs)
            query_vecs = l2_normalize(query_vecs)
        sims = query_vecs @ doc_vecs.T

        ranks = []
        by_quality: dict[str, list[int | None]] = defaultdict(list)
        by_type: dict[str, list[int | None]] = defaultdict(list)
        by_language: dict[str, list[int | None]] = defaultdict(list)
        misses: list[dict[str, Any]] = []
        top_examples: list[dict[str, Any]] = []
        doc_index = {doc["id"]: i for i, doc in enumerate(docs)}
        for qi, query in enumerate(queries):
            expected_any = query.get("expected_any_doc_ids") or [query.get("expected_doc_id")]
            expected_idx = {doc_index[e] for e in expected_any if e in doc_index}
            order = np.argsort(-sims[qi])[: args.top_k]
            rank = None
            for pos, idx in enumerate(order, start=1):
                if int(idx) in expected_idx:
                    rank = pos
                    break
            ranks.append(rank)
            by_quality[query["quality"]].append(rank)
            by_type[query["type"]].append(rank)
            by_language[str(query.get("language") or "unknown")].append(rank)
            if rank is None and len(misses) < 20:
                misses.append(
                    {
                        "query_id": query["id"],
                        "query": query["query"],
                        "expected": list(expected_any)[:5],
                        "top_hit_ids": [docs[int(i)]["id"] for i in order[:5]],
                        "top_hit_text": [docs[int(i)]["text"][:180] for i in order[:3]],
                    }
                )
            if len(top_examples) < 8:
                top_examples.append(
                    {
                        "query_id": query["id"],
                        "query": query["query"],
                        "rank": rank,
                        "top_hits": [
                            {
                                "rank": pos,
                                "id": docs[int(idx)]["id"],
                                "score": round(float(sims[qi, idx]), 6),
                                "source": docs[int(idx)]["source"],
                                "quality": docs[int(idx)]["quality"],
                                "type": docs[int(idx)]["type"],
                                "text": docs[int(idx)]["text"][:220],
                            }
                            for pos, idx in enumerate(order[:3], start=1)
                        ],
                    }
                )

        def agg(rank_list: list[int | None]) -> dict[str, float | int]:
            total = len(rank_list)
            hit1 = sum(1 for r in rank_list if r == 1)
            hit5 = sum(1 for r in rank_list if r is not None and r <= 5)
            hit10 = sum(1 for r in rank_list if r is not None and r <= 10)
            mrr = sum((1.0 / r) for r in rank_list if r) / total if total else 0.0
            return {
                "n": total,
                "recall_at_1": round(hit1 / total, 6) if total else 0.0,
                "recall_at_5": round(hit5 / total, 6) if total else 0.0,
                "recall_at_10": round(hit10 / total, 6) if total else 0.0,
                "mrr_at_10": round(mrr, 6),
            }

        vram_peak = None
        if args.device == "cuda" and torch.cuda.is_available():
            vram_peak = round(torch.cuda.max_memory_allocated() / 1024**3, 3)
        result.update(
            {
                "status": "ok",
                "dim": int(doc_vecs.shape[1]),
                "dim_ok": int(doc_vecs.shape[1]) == int(model_cfg["dim_expected"]),
                "load_sec": round(load_sec, 3),
                "network_code_fallback": network_code_fallback,
                "encode_sec": round(encode_sec, 3),
                "docs_per_sec": round((len(docs) + len(queries)) / encode_sec, 3) if encode_sec else None,
                "total_sec": round(time.time() - started, 3),
                "vram_peak_gb": vram_peak,
                "overall": agg(ranks),
                "by_quality": {k: agg(v) for k, v in sorted(by_quality.items())},
                "by_type": {k: agg(v) for k, v in sorted(by_type.items())},
                "by_language": {k: agg(v) for k, v in sorted(by_language.items())},
                "misses": misses,
                "top_examples": top_examples,
            }
        )
        del model, doc_vecs, query_vecs, sims
        gc.collect()
        if args.device == "cuda" and torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
        return result
    except Exception as exc:  # keep matrix running even when one model fails
        result.update(
            {
                "status": "error",
                "error_type": type(exc).__name__,
                "error": str(exc).splitlines()[0][:700],
                "total_sec": round(time.time() - started, 3),
            }
        )
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        return result


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    rows = []
    ok_results = [r for r in report["results"] if r.get("status") == "ok"]
    best = report.get("best_model") or {}
    lines = [
        "# Embedding Model Matrix Eval",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- model_root: `{report['model_root']}`",
        f"- docs: `{report['dataset']['doc_count']}`",
        f"- queries: `{report['dataset']['query_count']}`",
        f"- writes: `report files only; no Qdrant/Neo4j/production DB writes`",
        "",
        "## Decision",
        "",
    ]
    if best:
        lines.append(
            f"- Best overall: `{best['repo_id']}` with MRR@10 `{best['mrr_at_10']}` and R@5 `{best['recall_at_5']}`."
        )
    else:
        lines.append("- No model completed successfully.")
    lines.extend(
        [
            "- Keep production collection spaces isolated per model even when dimensions match.",
            "- Use this as retrieval evidence, not as permission to promote aliases or write production DBs.",
            "",
            "## Model Scores",
            "",
            "| rank | model | status | dim | MRR@10 | R@1 | R@5 | R@10 | encode sec | docs/sec | VRAM GB |",
            "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for idx, result in enumerate(report["ranked_results"], start=1):
        overall = result.get("overall") or {}
        rows.append(
            f"| {idx} | `{result['repo_id']}` | {result.get('status')} | {result.get('dim', '')} | "
            f"{overall.get('mrr_at_10', '')} | {overall.get('recall_at_1', '')} | "
            f"{overall.get('recall_at_5', '')} | {overall.get('recall_at_10', '')} | "
            f"{result.get('encode_sec', '')} | {result.get('docs_per_sec', '')} | {result.get('vram_peak_gb', '')} |"
        )
    lines.extend(rows)
    errors = [r for r in report["results"] if r.get("status") != "ok"]
    if errors:
        lines.extend(["", "## Load Errors", ""])
        for result in errors:
            lines.append(f"- `{result['repo_id']}`: `{result.get('status')}` {result.get('error_type', '')} {result.get('error', '')}")
    lines.extend(["", "## Dataset Mix", ""])
    for key, value in report["dataset"]["source_counts"].items():
        lines.append(f"- `{key}`: `{value}` docs")
    lines.extend(["", "## Quality Slice Winners", ""])
    qualities = sorted({q for r in ok_results for q in (r.get("by_quality") or {})})
    for quality in qualities:
        winner = max(
            ok_results,
            key=lambda r: ((r.get("by_quality") or {}).get(quality) or {}).get("mrr_at_10", -1),
            default=None,
        )
        if winner:
            metrics = (winner.get("by_quality") or {}).get(quality) or {}
            lines.append(f"- `{quality}`: `{winner['repo_id']}` MRR@10 `{metrics.get('mrr_at_10')}` R@5 `{metrics.get('recall_at_5')}` n `{metrics.get('n')}`")
    lines.extend(["", "## Language Slice Winners", ""])
    languages = sorted({lang for r in ok_results for lang in (r.get("by_language") or {})})
    for language in languages:
        winner = max(
            ok_results,
            key=lambda r: ((r.get("by_language") or {}).get(language) or {}).get("mrr_at_10", -1),
            default=None,
        )
        if winner:
            metrics = (winner.get("by_language") or {}).get(language) or {}
            lines.append(f"- `{language}`: `{winner['repo_id']}` MRR@10 `{metrics.get('mrr_at_10')}` R@5 `{metrics.get('recall_at_5')}` n `{metrics.get('n')}`")
    lines.extend(["", "## Notes", ""])
    lines.append("- Scores use synthetic source-grounded queries generated from existing artifacts.")
    lines.append("- Fixed-domain probes are included, but main ranking uses document-specific expected hits.")
    lines.append("- Model selection must be read by language slice, quality slice, and type slice; a high overall score is not enough for promotion.")
    lines.append("- English-only `BAAI/bge-large-en-v1.5` is expected to underperform Chinese/multilingual cases.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out-dir", type=Path, default=Path("reports/embedding_model_matrix_eval_20260517"))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-seq-length", type=int, default=512)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--stable-limit", type=int, default=650)
    parser.add_argument("--legacy-limit", type=int, default=250)
    parser.add_argument("--ocr-limit", type=int, default=220)
    parser.add_argument("--sidecar-limit", type=int, default=90)
    parser.add_argument("--models-json", type=Path, help="Optional JSON model config list")
    parser.add_argument("--assume-normalized", action="store_true")
    parser.add_argument("--allow-network-code", action="store_true", help="Allow missing trust_remote_code modules to be fetched into D: HF cache.")
    args = parser.parse_args(argv)

    os.environ.setdefault("HF_HOME", r"D:\AI\hf_home")
    os.environ.setdefault("HF_HUB_CACHE", r"D:\AI\hf_cache\hub")
    os.environ.setdefault("HF_XET_CACHE", r"D:\AI\hf_cache\xet")
    os.environ.setdefault("HF_MODULES_CACHE", r"D:\AI\hf_modules")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    if args.allow_network_code:
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "0")
        os.environ.setdefault("HF_HUB_OFFLINE", "0")
    else:
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")

    root = args.repo_root
    out_dir = args.out_dir
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    models = json.loads(args.models_json.read_text(encoding="utf-8")) if args.models_json else DEFAULT_MODELS
    docs, queries, source_counts = build_dataset(root, args)
    dataset_path = out_dir / "eval_dataset.json"
    dataset_path.write_text(
        json.dumps({"docs": docs, "queries": queries, "source_counts": source_counts}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"dataset docs={len(docs)} queries={len(queries)} out={dataset_path}", flush=True)

    results = []
    for model_cfg in models:
        print(f"MODEL_START {model_cfg['repo_id']}", flush=True)
        result = score_model(model_cfg, docs, queries, args)
        print(
            "MODEL_DONE "
            + json.dumps(
                {
                    "repo_id": result["repo_id"],
                    "status": result["status"],
                    "overall": result.get("overall"),
                    "dim": result.get("dim"),
                    "error": result.get("error"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        results.append(result)
        (out_dir / "embedding_model_matrix_eval.partial.json").write_text(
            json.dumps({"results": results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    ok_results = [r for r in results if r.get("status") == "ok"]
    ranked_results = sorted(
        results,
        key=lambda r: (
            1 if r.get("status") == "ok" else 0,
            (r.get("overall") or {}).get("mrr_at_10", -1),
            (r.get("overall") or {}).get("recall_at_5", -1),
        ),
        reverse=True,
    )
    best = None
    if ok_results:
        winner = ranked_results[0]
        best = {
            "repo_id": winner["repo_id"],
            "mrr_at_10": (winner.get("overall") or {}).get("mrr_at_10"),
            "recall_at_5": (winner.get("overall") or {}).get("recall_at_5"),
        }
    report = {
        "schema_version": "embedding_model_matrix_eval.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "repo_root": str(root),
        "model_root": r"D:\AI\models\embeddings",
        "execution_policy": "local artifacts and local D: models only; no production DB writes",
        "dataset": {
            "doc_count": len(docs),
            "query_count": len(queries),
            "source_counts": source_counts,
        },
        "best_model": best,
        "results": results,
        "ranked_results": ranked_results,
    }
    json_path = out_dir / "embedding_model_matrix_eval.json"
    md_path = out_dir / "embedding_model_matrix_eval.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(md_path, report)
    print(f"REPORT_JSON {json_path}", flush=True)
    print(f"REPORT_MD {md_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
