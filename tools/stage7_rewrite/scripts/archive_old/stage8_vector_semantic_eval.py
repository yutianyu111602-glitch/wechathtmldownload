#!/usr/bin/env python3
"""Run in-memory vector quality canaries for Stage8 card templates.

This script embeds a bounded sample and fixed golden queries, then ranks jobs in
memory. It does not write Qdrant, Neo4j, or PC DB production data.
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib import parse, request

import yaml

if __name__ == "__main__" and not __package__:
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))

from stage7.atomic_io import safe_read_json
from stage7.vector_plan.build_embedding_jobs import build_jobs_from_article, iter_ocr_evidence
from stage7.vector_plan.enrichment import clean_account, infer_city, infer_venue
from stage7.vector_plan.schemas import VectorJob

SCORE_PROFILES = (
    "cosine",
    "soft_payload",
    "intent_v2",
    "source_adaptive",
    "adaptive_v3",
    "adaptive_v3_source_guard",
    "adaptive_v4_source_gate",
)

LEXICAL_STOP_TERMS = {
    "活动",
    "派对",
    "电子音乐",
    "场地",
    "酒吧",
    "俱乐部",
    "周末",
    "本周末",
    "今晚",
    "周五",
    "周六",
    "阵容",
    "event",
    "party",
    "club",
    "bar",
    "venue",
    "weekend",
    "show",
}

MAJOR_CITY_NEGATIVE_TERMS = ["北京", "上海", "深圳", "广州", "成都", "杭州", "济南", "昆明", "厦门"]

GOLDEN_QUERIES = [
    {
        "id": "beijing_dada_event",
        "query": "北京 Dada 酒吧 5月4日 原力青年迪斯科 活动",
        "expected_groups": [["dada"], ["北京", "beijing"], ["原力青年迪斯科"]],
        "city": "北京",
        "preferred_kinds": ["event", "article", "entity_identity", "entity_mention", "entity"],
    },
    {
        "id": "kunming_dada_event",
        "query": "昆明 Dada 活动 虹山 有集",
        "expected_groups": [["dada"], ["kunming", "昆明"], ["虹山", "有集"]],
        "city": "昆明",
        "preferred_kinds": ["event", "article", "entity_identity", "entity_mention", "entity"],
        "negative_terms": ["jinal", "jinan", "济南", "KEY JINAN"],
    },
    {
        "id": "shanghai_exit_club",
        "query": "上海 EXIT 俱乐部 电子音乐 活动",
        "expected_groups": [["exit"], ["上海", "shanghai"]],
        "city": "上海",
        "preferred_kinds": ["event", "article", "entity_identity", "entity_mention", "entity"],
    },
    {
        "id": "xiamen_twinklab_venue",
        "query": "厦门 蜕壳 TwinKlab 俱乐部 场地",
        "expected_groups": [["厦门", "xiamen"], ["twinklab", "蜕壳"]],
        "city": "厦门",
        "preferred_kinds": ["entity_identity", "entity_mention", "entity", "article"],
    },
    {
        "id": "weekly_party_events",
        "query": "本周末 电子音乐 派对 阵容 场地",
        "expected_groups": [["派对", "活动", "party"], ["阵容", "lineup", "club", "俱乐部"]],
        "generic_intent": "event",
        "preferred_kinds": ["event", "article"],
    },
    {
        "id": "jinan_key_club",
        "query": "济南 KEY JINAN 俱乐部 活动",
        "expected_groups": [["key jinan"], ["济南", "jinan"], ["club", "俱乐部", "venue", "场地"]],
        "city": "济南",
        "preferred_kinds": ["event", "article", "entity_identity", "entity_mention", "entity"],
        "negative_terms": ["dada", "昆明", "北京"],
    },
    {
        "id": "shenzhen_oil_club",
        "query": "深圳 OIL CLUB 电子音乐 活动",
        "expected_groups": [["oil"], ["深圳", "shenzhen"], ["club", "俱乐部"]],
        "city": "深圳",
        "preferred_kinds": ["event", "article", "entity_identity", "entity_mention", "entity"],
        "negative_terms": ["key jinan", "济南", "昆明"],
    },
    {
        "id": "beijing_zhaodai_weekend",
        "query": "北京 招待 ZhaoDai 周六 weekend 活动",
        "expected_groups": [["zhaodai", "招待"], ["北京", "beijing"], ["周六", "weekend", "活动"]],
        "city": "北京",
        "preferred_kinds": ["event", "article", "entity_identity", "entity_mention", "entity"],
    },
    {
        "id": "shanghai_all_club",
        "query": "上海 ALL Club All俱乐部 电子音乐",
        "expected_groups": [["all club", "all俱乐部"], ["上海", "shanghai"]],
        "city": "上海",
        "preferred_kinds": ["event", "article", "entity_identity", "entity_mention", "entity"],
    },
    {
        "id": "hangzhou_electronic_scene",
        "query": "杭州 电子音乐 俱乐部 派对 场地",
        "expected_groups": [["杭州", "hangzhou"], ["俱乐部", "club", "电子"]],
        "city": "杭州",
        "preferred_kinds": ["event", "article", "entity_identity", "entity_mention", "entity"],
    },
    {
        "id": "nanjing_underground_event",
        "query": "南京 地下 电子 活动 live",
        "expected_groups": [["南京", "nanjing"], ["地下", "电子", "活动"]],
        "city": "南京",
        "preferred_kinds": ["event", "article", "entity_identity", "entity_mention"],
    },
]


def endpoint_port(endpoint: str) -> int:
    parsed = parse.urlparse(endpoint)
    if parsed.port is not None:
        return int(parsed.port)
    return 443 if parsed.scheme == "https" else 80


def load_vector_route(
    root: Path,
    endpoint_override: str | None = None,
    model_override: str | None = None,
    dim_override: int | None = None,
) -> tuple[str, str, int, dict[str, Any]]:
    config_path = root / "config" / "vector_endpoints.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    key = data.get("default_chinese_endpoint", "local_mac_vector_endpoint_11437")
    ep = data.get("endpoints", {}).get(key, {})
    endpoint = endpoint_override or ep.get("pc_call_url") or ep.get("url") or "http://192.168.8.234:11437"
    model = model_override or ep.get("model", "stella-large-zh-v2")
    dim = int(dim_override or ep.get("dim", 1024))
    override_active = bool(endpoint_override or model_override or dim_override)
    route = {
        "endpoint_id": ("candidate_model_override" if override_active else ep.get("endpoint_id")) or key,
        "endpoint_port": endpoint_port(endpoint),
        "canonical_url": ep.get("canonical_url", ""),
        "pc_call_url": endpoint,
        "route_role": "candidate_model_eval" if override_active else ep.get("route_role", "wechat_93k_default"),
        "dim_expected": dim,
    }
    return endpoint, model, dim, route


def iter_extract_files(output_root: Path, sample: int, extract_scope: str = "primary") -> list[Path]:
    if extract_scope == "primary":
        files = sorted((output_root / "llm_extract").rglob("extract.article.v1.json"))
    elif extract_scope == "all":
        files = sorted(output_root.rglob("extract.article.v1.json"))
    else:
        raise ValueError(f"unknown extract_scope={extract_scope}")
    priority_terms = ["dada", "exit", "twinklab", "蜕壳", "北京", "昆明", "上海", "厦门", "oil", "key jinan"]
    selected: list[Path] = []
    seen: set[Path] = set()
    hay_cache: dict[Path, str] = {}
    for path in files:
        raw = path.read_text(encoding="utf-8", errors="replace")
        hay_cache[path] = (raw + " " + str(path)).lower()

    for query in GOLDEN_QUERIES:
        groups = query.get("expected_groups", [])
        if not groups:
            continue
        city = str(query.get("city", "")).lower()
        selection_groups = [
            group for group in groups
            if not city or not any(term.lower() == city for term in group)
        ]
        for path in files:
            hay = hay_cache[path]
            if all(any(term.lower() in hay for term in group) for group in selection_groups):
                selected.append(path)
                seen.add(path)
                break
        if len(selected) >= sample:
            return selected[:sample]

    scored: list[tuple[int, str, Path]] = []
    for path in files:
        if path in seen:
            continue
        hay = hay_cache[path]
        score = sum(1 for term in priority_terms if term.lower() in hay)
        scored.append((-score, str(path), path))
    selected.extend(path for _, _, path in sorted(scored))
    return selected[:sample]


def build_variant_jobs(
    root: Path,
    output_root: Path,
    template: str,
    sample: int,
    max_jobs: int,
    endpoint_override: str | None = None,
    model_override: str | None = None,
    dim_override: int | None = None,
) -> list[VectorJob]:
    return build_variant_jobs_from_files(
        root,
        output_root,
        template,
        iter_extract_files(output_root, sample),
        max_jobs,
        endpoint_override=endpoint_override,
        model_override=model_override,
        dim_override=dim_override,
    )


def build_variant_jobs_from_files(
    root: Path,
    output_root: Path,
    template: str,
    extract_files: list[Path],
    max_jobs: int,
    endpoint_override: str | None = None,
    model_override: str | None = None,
    dim_override: int | None = None,
) -> list[VectorJob]:
    endpoint, model, dim, route = load_vector_route(
        root,
        endpoint_override=endpoint_override,
        model_override=model_override,
        dim_override=dim_override,
    )
    jobs: list[VectorJob] = []
    for path in extract_files:
        article = safe_read_json(path, {})
        if not article:
            continue
        rel = str(path.relative_to(output_root))
        jobs.extend(build_jobs_from_article(article, rel, model, endpoint, dim, route, card_template=template))
        if max_jobs > 0 and len(jobs) >= max_jobs:
            return jobs[:max_jobs]
    return jobs[:max_jobs] if max_jobs > 0 else jobs


def embed_text(endpoint: str, model: str, text: str, expected_dim: int, timeout: int = 60) -> list[float]:
    body = json.dumps({"model": model, "input": text}).encode("utf-8")
    req = request.Request(
        f"{endpoint.rstrip('/')}/v1/embeddings",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    vector = payload["data"][0]["embedding"]
    if len(vector) != expected_dim:
        raise ValueError(f"dim_mismatch expected={expected_dim} actual={len(vector)}")
    return [float(v) for v in vector]


def embedding_cache_key(endpoint: str, model: str, expected_dim: int, text: str) -> str:
    raw = "\0".join([endpoint.rstrip("/"), model, str(expected_dim), text])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class EmbeddingCache:
    """Small JSON cache for repeatable local semantic eval runs."""

    def __init__(self, path: Path):
        self.path = path
        self.vectors: dict[str, list[float]] = {}
        self.hits = 0
        self.misses = 0
        self.dirty = False
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.vectors = {
                str(key): [float(v) for v in value]
                for key, value in (payload.get("vectors", {}) or {}).items()
            }

    def get_or_embed(
        self,
        endpoint: str,
        model: str,
        text: str,
        expected_dim: int,
        embedder=embed_text,
    ) -> list[float]:
        key = embedding_cache_key(endpoint, model, expected_dim, text)
        vector = self.vectors.get(key)
        if vector is not None:
            self.hits += 1
            return vector
        self.misses += 1
        vector = embedder(endpoint, model, text, expected_dim)
        self.vectors[key] = vector
        self.dirty = True
        return vector

    def save(self) -> None:
        if not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "stage8_embedding_cache.v1",
            "vector_count": len(self.vectors),
            "vectors": self.vectors,
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self.dirty = False

    def stats(self) -> dict[str, int | str]:
        return {
            "path": str(self.path),
            "vector_count": len(self.vectors),
            "hits": self.hits,
            "misses": self.misses,
        }


def normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm <= 0:
        return vector
    return [v / norm for v in vector]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def term_hit(job: VectorJob, terms: list[str]) -> bool:
    hay = (job.canonical_text + " " + json.dumps(job.metadata, ensure_ascii=False)).lower()
    return any(term.lower() in hay for term in terms)


def grouped_term_hit(job: VectorJob, query: dict[str, Any]) -> bool:
    if query.get("generic_intent") == "event":
        if job.object_kind == "event":
            return True
        if job.object_kind == "article":
            return term_hit(job, ["活动", "派对", "party", "night", "club", "阵容"])
    hay = (job.canonical_text + " " + json.dumps(job.metadata, ensure_ascii=False)).lower()
    groups = query.get("expected_groups")
    if groups:
        return all(any(term.lower() in hay for term in group) for group in groups)
    return term_hit(job, query.get("expected_terms", []))


def query_specific_terms(query: dict[str, Any]) -> list[str]:
    text = str(query.get("query", "")).lower()
    city = str(query.get("city", "")).lower()
    tokens = re.findall(r"[0-9]+月[0-9]+日?|[a-zA-Z][a-zA-Z0-9_-]+|[\u4e00-\u9fff]{2,}", text)
    terms: list[str] = []
    for token in tokens:
        token = token.lower()
        if len(token) < 2:
            continue
        if token == city or token in LEXICAL_STOP_TERMS:
            continue
        if token not in terms:
            terms.append(token)
    return terms


def significant_terms(text: str, limit: int = 3) -> list[str]:
    """Extract compact terms that are useful for generated eval queries."""
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+|[\u4e00-\u9fff]{2,}", str(text).lower())
    terms: list[str] = []
    for token in tokens:
        if token in LEXICAL_STOP_TERMS:
            continue
        if token not in terms:
            terms.append(token)
        if len(terms) >= limit:
            break
    return terms


def object_terms(obj: dict[str, Any], fallback: str = "", limit: int = 3) -> list[str]:
    values = [obj.get("name", ""), fallback]
    values.extend(obj.get("aliases", []) or [])
    terms: list[str] = []
    for value in values:
        value = str(value).strip()
        if not value:
            continue
        if len(value) <= 40 and value.lower() not in terms:
            terms.append(value.lower())
        for term in significant_terms(value, limit=limit):
            if term not in terms:
                terms.append(term)
        if len(terms) >= limit:
            break
    return terms[:limit]


def auto_queries_for_article(article: dict[str, Any], source_path: str, per_article_limit: int = 4) -> list[dict[str, Any]]:
    """Generate labeled eval queries from one extract file.

    These are still weak-label canaries: they verify retrieval shape and rerank
    behavior on existing extracted objects, not human-reviewed ground truth.
    """
    queries: list[dict[str, Any]] = []
    seen_query_text: set[str] = set()

    def add_query(query: dict[str, Any]) -> None:
        text = str(query.get("query", "")).strip()
        if not text:
            return
        key = text.lower()
        if key in seen_query_text:
            return
        seen_query_text.add(key)
        queries.append(query)
    article_id = str(article.get("article_id") or article.get("article_uid") or "article")
    account = clean_account(str(article.get("source_account", "")))
    city = infer_city(article)
    title = str(article.get("title", "")).strip()
    title_terms = significant_terms(title, limit=3)
    account_terms = significant_terms(account, limit=2) or ([account.lower()] if account else [])

    if account_terms:
        expected_groups = [account_terms[:2]]
        if city:
            expected_groups.insert(0, [city])
        add_query(
            {
                "id": f"auto_account:{article_id}:profile",
                "query": " ".join(p for p in [city, account, "公众号 账号 近期活动 场地画像"] if p),
                "expected_groups": expected_groups,
                "city": city,
                "intent": "account_lookup",
                "preferred_kinds": ["account_profile", "article", "event", "entity_identity", "entity_mention", "entity"],
                "source_path": source_path,
            }
        )

    if title_terms and account_terms:
        expected_groups = [account_terms[:2], title_terms[:2]]
        if city:
            expected_groups.insert(0, [city])
        add_query(
            {
                "id": f"auto_article:{article_id}:account_title",
                "query": " ".join(p for p in [city, account, " ".join(title_terms), "活动 文章"] if p),
                "expected_groups": expected_groups,
                "city": city,
                "intent": "article_lookup",
                "preferred_kinds": ["article", "event", "entity_identity", "entity_mention", "entity"],
                "source_path": source_path,
            }
        )
        add_query(
            {
                "id": f"auto_article:{article_id}:title_only",
                "query": " ".join(p for p in [city, " ".join(title_terms), "微信公众号 推文"] if p),
                "expected_groups": expected_groups[-1:],
                "city": city,
                "intent": "article_lookup",
                "preferred_kinds": ["article", "event", "entity_identity", "entity_mention", "entity"],
                "source_path": source_path,
            }
        )

    for idx, obj in enumerate(article.get("events", []) or []):
        terms = object_terms(obj, fallback=title, limit=3)
        if not terms:
            continue
        event_city = infer_city(article, obj) or city
        groups = [terms[:2]]
        if event_city:
            groups.insert(0, [event_city])
        venue = str(obj.get("place", "") or infer_venue(article, obj)).strip()
        add_query(
            {
                "id": f"auto_event:{article_id}:{idx}:full",
                "query": " ".join(p for p in [event_city, account, " ".join(terms), venue, "活动 阵容 场地"] if p),
                "expected_groups": groups,
                "city": event_city,
                "intent": "event_lookup",
                "preferred_kinds": ["event", "article", "entity_identity", "entity_mention", "entity"],
                "source_path": source_path,
            }
        )
        add_query(
            {
                "id": f"auto_event:{article_id}:{idx}:lineup",
                "query": " ".join(p for p in [event_city, " ".join(terms), "lineup 阵容 DJ"] if p),
                "expected_groups": groups,
                "city": event_city,
                "intent": "event_lookup",
                "preferred_kinds": ["event", "article", "entity_identity", "entity_mention", "entity"],
                "source_path": source_path,
            }
        )

    for idx, obj in enumerate(article.get("entities", []) or []):
        if len(queries) >= per_article_limit:
            break
        etype = str(obj.get("type", "")).lower()
        if etype not in {"organization", "place", "person", "event", "activity", "party", "show", "festival", "concert", "gig", "活动", "派对", "演出"}:
            continue
        terms = object_terms(obj, fallback=title, limit=3)
        if not terms:
            continue
        obj_city = infer_city(article, obj) or city
        venue = infer_venue(article, obj)
        groups = [terms[:2]]
        if obj_city:
            groups.insert(0, [obj_city])
        if etype == "person":
            intent = "person_lookup"
            suffix = "DJ 艺人 阵容 活动"
            preferred = ["entity_identity", "entity_mention", "entity", "event", "article"]
        elif etype in {"event", "activity", "party", "show", "festival", "concert", "gig", "活动", "派对", "演出"}:
            intent = "event_lookup"
            suffix = "活动 阵容 场地"
            preferred = ["event", "article", "entity_identity", "entity_mention", "entity"]
        else:
            intent = "venue_lookup"
            suffix = "俱乐部 场地 活动"
            preferred = ["entity_identity", "entity_mention", "entity", "event", "article"]
        base = {
            "expected_groups": groups,
            "city": obj_city,
            "intent": intent,
            "entity_type": etype,
            "preferred_kinds": preferred,
            "source_path": source_path,
        }
        add_query(
            {
                **base,
                "id": f"auto_entity:{article_id}:{idx}:full",
                "query": " ".join(p for p in [obj_city, " ".join(terms), venue if venue not in terms else "", account, suffix] if p),
            }
        )
        add_query(
            {
                **base,
                "id": f"auto_entity:{article_id}:{idx}:name_city",
                "query": " ".join(p for p in [obj_city, " ".join(terms), suffix] if p),
            }
        )
        if intent == "person_lookup":
            add_query(
                {
                    **base,
                    "id": f"auto_entity:{article_id}:{idx}:person_lineup",
                    "query": " ".join(p for p in [" ".join(terms), account, "DJ 艺人 阵容 哪场活动"] if p),
                }
            )
        elif intent == "venue_lookup":
            add_query(
                {
                    **base,
                    "id": f"auto_entity:{article_id}:{idx}:venue_events",
                    "query": " ".join(p for p in [obj_city, " ".join(terms), "近期活动 场地 俱乐部"] if p),
                }
            )

    for idx, ocr in enumerate(iter_ocr_evidence(article)):
        if len(queries) >= per_article_limit:
            break
        ocr_terms = significant_terms(str(ocr.get("ocr_text", "")), limit=3)
        if not ocr_terms:
            continue
        groups = [ocr_terms[:2]]
        if city:
            groups.insert(0, [city])
        add_query(
            {
                "id": f"auto_ocr:{article_id}:{idx}:evidence",
                "query": " ".join(p for p in [city, " ".join(ocr_terms), account, "海报 OCR 图片证据 活动"] if p),
                "expected_groups": groups,
                "city": city,
                "intent": "ocr_evidence_lookup",
                "preferred_kinds": ["ocr_evidence", "event", "article", "entity_identity", "entity_mention", "entity"],
                "source_path": source_path,
            }
        )

    return queries[:per_article_limit]


def source_lane_from_values(source_account: str = "", source_path: str = "") -> str:
    account = str(source_account or "").lower()
    if "__" in account:
        return account.split("__", 1)[0]
    path = str(source_path or "").lower()
    for marker in (
        "latest_free",
        "latest_dajiala_canary",
        "free_signed_reexported",
        "full_empty_wave_0001_review",
        "full_empty_wave_0002_review",
        "full_empty_wave_0001_recovered",
        "full_empty_wave_0002_recovered",
    ):
        if marker in path:
            return marker
    if "review" in account or "review" in path:
        return "review"
    if "recovered" in account or "recovered" in path:
        return "recovered"
    return ""


def hard_negative_queries_for_article(article: dict[str, Any], source_path: str, per_article_limit: int = 4) -> list[dict[str, Any]]:
    """Generate harder eval probes for city/source leakage.

    These queries are diagnostic probes. They are not human labels; they are
    designed to expose review-lane and cross-city leakage that easy weak labels
    can hide.
    """
    queries: list[dict[str, Any]] = []
    seen_query_text: set[str] = set()

    def add_query(query: dict[str, Any]) -> None:
        text = str(query.get("query", "")).strip()
        if not text:
            return
        key = text.lower()
        if key in seen_query_text:
            return
        seen_query_text.add(key)
        query.setdefault("query_source", "hard_negative")
        query.setdefault("hard_negative", True)
        queries.append(query)

    article_id = str(article.get("article_id") or article.get("article_uid") or "article")
    account = clean_account(str(article.get("source_account", "")))
    city = infer_city(article)
    title = str(article.get("title", "")).strip()
    lane = source_lane_from_values(str(article.get("source_account", "")), source_path)
    account_terms = significant_terms(account, limit=2) or ([account.lower()] if account else [])
    title_terms = significant_terms(title, limit=2)
    core_terms = account_terms or title_terms
    if not core_terms:
        for obj in (article.get("entities", []) or [])[:3]:
            core_terms.extend(object_terms(obj, fallback=title, limit=2))
            if core_terms:
                break
    if not core_terms:
        return []

    groups = [core_terms[:2]]
    if city:
        groups.insert(0, [city])

    if "review" in lane:
        add_query(
            {
                "id": f"hard_source_gate:{article_id}:review_lane",
                "query": " ".join(p for p in [city, " ".join(core_terms[:2]), " ".join(title_terms[:2]), "活动 来源质量"] if p),
                "expected_groups": groups,
                "city": city,
                "intent": "venue_lookup",
                "preferred_kinds": ["entity_identity", "entity_mention", "event", "article", "entity"],
                "hard_negative_type": "source_quality_gate",
                "min_top1_source_quality": 0.8,
                "source_path": source_path,
            }
        )

    if city:
        negative_terms = [term for term in MAJOR_CITY_NEGATIVE_TERMS if term != city]
        add_query(
            {
                "id": f"hard_city:{article_id}:city_disambiguation",
                "query": " ".join(p for p in [city, " ".join(core_terms[:2]), "俱乐部 场地 活动 不要串城市"] if p),
                "expected_groups": groups,
                "city": city,
                "intent": "venue_lookup",
                "preferred_kinds": ["entity_identity", "entity_mention", "event", "article", "entity"],
                "negative_terms": negative_terms,
                "hard_negative_type": "city_disambiguation",
                "source_path": source_path,
            }
        )

    return queries[:per_article_limit]


def build_hard_negative_queries(
    output_root: Path,
    extract_files: list[Path],
    hard_negative_limit: int = 120,
    hard_negative_per_article: int = 4,
) -> list[dict[str, Any]]:
    generated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in extract_files:
        article = safe_read_json(path, {})
        if not article:
            continue
        try:
            rel = str(path.relative_to(output_root))
        except ValueError:
            rel = str(path)
        for query in hard_negative_queries_for_article(article, rel, per_article_limit=hard_negative_per_article):
            key = query["query"].lower()
            if key in seen:
                continue
            seen.add(key)
            generated.append(query)
            if len(generated) >= hard_negative_limit:
                break
        if len(generated) >= hard_negative_limit:
            break
    return generated


def tagged_queries(queries: list[dict[str, Any]], query_source: str) -> list[dict[str, Any]]:
    tagged = []
    for query in queries:
        item = dict(query)
        item.setdefault("query_source", query_source)
        tagged.append(item)
    return tagged


def build_eval_queries(
    output_root: Path,
    extract_files: list[Path],
    query_mode: str = "fixed",
    auto_query_limit: int = 120,
    auto_query_per_article: int = 4,
    hard_negative_limit: int = 120,
    hard_negative_per_article: int = 4,
) -> list[dict[str, Any]]:
    fixed_queries = tagged_queries(list(GOLDEN_QUERIES), "fixed")
    if query_mode == "fixed":
        return fixed_queries
    generated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in extract_files:
        article = safe_read_json(path, {})
        if not article:
            continue
        try:
            rel = str(path.relative_to(output_root))
        except ValueError:
            rel = str(path)
        for query in auto_queries_for_article(article, rel, per_article_limit=auto_query_per_article):
            key = query["query"].lower()
            if key in seen:
                continue
            query = dict(query)
            query.setdefault("query_source", "auto")
            seen.add(key)
            generated.append(query)
            if len(generated) >= auto_query_limit:
                break
        if len(generated) >= auto_query_limit:
            break
    hard_negative_queries = build_hard_negative_queries(
        output_root,
        extract_files,
        hard_negative_limit=hard_negative_limit,
        hard_negative_per_article=hard_negative_per_article,
    )
    if query_mode == "auto":
        return generated
    if query_mode == "combined":
        return fixed_queries + generated
    if query_mode == "hard":
        return hard_negative_queries
    if query_mode == "combined_hard":
        return fixed_queries + generated + hard_negative_queries
    raise ValueError(f"unknown query_mode={query_mode}")


def lexical_overlap_score(query: dict[str, Any], job: VectorJob) -> float:
    terms = query_specific_terms(query)
    if not terms:
        return 0.0
    hay = (job.canonical_text + " " + json.dumps(job.metadata, ensure_ascii=False)).lower()
    hits = sum(1 for term in terms if term in hay)
    return hits / len(terms)


def payload_match(query: dict[str, Any], job: VectorJob) -> float:
    score = 0.0
    metadata = job.metadata or {}
    if query.get("city"):
        city = str(metadata.get("city", ""))
        if city == query["city"]:
            score += 1.0
        elif city:
            score -= 0.5
    if job.object_kind in set(query.get("preferred_kinds", [])):
        score += 0.5
    if term_hit(job, query.get("negative_terms", [])):
        score -= 1.0
    return score


def query_intent_bonus(query: dict[str, Any], job: VectorJob) -> float:
    text = str(query.get("query", "")).lower()
    kind = job.object_kind
    score = 0.0
    lexical = lexical_overlap_score(query, job)
    has_specific_terms = bool(query_specific_terms(query))
    event_terms = ("活动", "派对", "今晚", "周末", "周六", "周五", "阵容", "party", "festival", "weekend", "show")
    venue_terms = ("场地", "俱乐部", "酒吧", "club", "venue", "bar")
    account_terms = ("公众号", "账号", "account", "source", "来源号", "画像")
    ocr_terms = ("ocr", "海报", "图片", "poster", "视觉", "识别")
    if any(term in text for term in account_terms):
        if kind == "account_profile":
            score += 0.85 if not has_specific_terms else 0.35 + 0.65 * lexical
        elif kind == "article":
            score += 0.25 if not has_specific_terms else 0.1 + 0.25 * lexical
    if any(term in text for term in ocr_terms):
        if kind == "ocr_evidence":
            score += 0.9 if not has_specific_terms else 0.35 + 0.7 * lexical
        elif kind == "event":
            score += 0.2 if not has_specific_terms else 0.1 + 0.25 * lexical
        elif kind == "article":
            score += 0.15 if not has_specific_terms else 0.05 + 0.2 * lexical
    if any(term in text for term in event_terms):
        if kind == "event":
            score += 0.75 if not has_specific_terms else 0.2 + 0.7 * lexical
        elif kind == "article":
            score += 0.35 if not has_specific_terms else 0.1 + 0.35 * lexical
        elif kind in {"entity_mention", "entity_identity", "entity"}:
            score += 0.1 if not has_specific_terms else 0.1 + 0.25 * lexical
    if any(term in text for term in venue_terms):
        if kind in {"entity_identity", "entity_mention", "entity"}:
            score += 0.45 if not has_specific_terms else 0.2 + 0.35 * lexical
        elif kind == "event":
            score += 0.2 if not has_specific_terms else 0.1 + 0.2 * lexical
    return score


def payload_match_v2(query: dict[str, Any], job: VectorJob) -> float:
    score = 0.0
    metadata = job.metadata or {}
    if query.get("city"):
        city = str(metadata.get("city", ""))
        if city == query["city"]:
            score += 1.4
        elif city:
            score -= 1.2
        else:
            score -= 0.25
    if job.object_kind in set(query.get("preferred_kinds", [])):
        score += 0.6
    score += query_intent_bonus(query, job)
    score += 0.4 * lexical_overlap_score(query, job)
    if term_hit(job, query.get("negative_terms", [])):
        score -= 1.5
    return score


def normalized_query_intent(query: dict[str, Any]) -> str:
    intent = str(query.get("intent", "")).strip().lower()
    if intent:
        return intent
    if query.get("generic_intent") == "event":
        return "broad_event"
    text = str(query.get("query", "")).lower()
    if any(term in text for term in ("公众号", "账号", "account", "source", "来源号", "画像")):
        return "account_lookup"
    if any(term in text for term in ("ocr", "海报", "图片", "poster", "视觉", "识别")):
        return "ocr_evidence_lookup"
    if any(term in text for term in ("dj", "艺人", "artist", "阵容")):
        return "person_lookup"
    if any(term in text for term in ("活动", "派对", "festival", "party", "show", "weekend", "周末")):
        return "event_lookup"
    if any(term in text for term in ("场地", "俱乐部", "酒吧", "club", "venue", "bar")):
        return "venue_lookup"
    return "semantic_lookup"


def intent_kind_score(query: dict[str, Any], job: VectorJob) -> float:
    intent = normalized_query_intent(query)
    kind = job.object_kind
    metadata = job.metadata or {}
    entity_type = str(metadata.get("entity_type", query.get("entity_type", ""))).lower()
    if intent == "account_lookup":
        if kind == "account_profile":
            return 1.0
        if kind == "article":
            return 0.5
        if kind == "event":
            return 0.3
        if kind in {"entity_identity", "entity_mention", "entity"}:
            return 0.2
        return 0.1
    if intent == "ocr_evidence_lookup":
        if kind == "ocr_evidence":
            return 1.0
        if kind == "event":
            return 0.5
        if kind == "article":
            return 0.35
        if kind in {"entity_identity", "entity_mention", "entity"}:
            return 0.25
        return 0.1
    if intent in {"event_lookup", "broad_event"}:
        if kind == "event":
            return 1.0
        if kind == "article":
            return 0.55
        if kind in {"entity_identity", "entity_mention", "entity"} and entity_type in {"event", "activity", "party", "show", "festival", "concert", "gig", "活动", "派对", "演出"}:
            return 0.45
        return 0.15
    if intent == "venue_lookup":
        if kind in {"entity_identity", "entity_mention", "entity"} and entity_type in {"organization", "place", "venue", "club", "bar", ""}:
            return 1.0
        if kind == "article":
            return 0.35
        if kind == "event":
            return 0.25
        return 0.1
    if intent == "person_lookup":
        if kind in {"entity_identity", "entity_mention", "entity"} and entity_type in {"person", "artist", "dj", ""}:
            return 1.0
        if kind == "event":
            return 0.4
        if kind == "article":
            return 0.3
        return 0.1
    if intent == "article_lookup":
        if kind == "article":
            return 1.0
        if kind == "event":
            return 0.45
        if kind in {"entity_identity", "entity_mention", "entity"}:
            return 0.3
        return 0.1
    return 0.3


def candidate_prefilter_score(query: dict[str, Any], job: VectorJob) -> float:
    """Cheap metadata/lexical score used before vector rerank at large scale."""
    metadata = job.metadata or {}
    score = 0.0
    query_city = str(query.get("city", ""))
    job_city = str(metadata.get("city", ""))
    if query_city:
        if job_city == query_city:
            score += 2.0
        elif job_city:
            score -= 2.0
        else:
            score -= 0.2
    lexical = lexical_overlap_score(query, job)
    score += 2.4 * lexical
    score += 1.2 * intent_kind_score(query, job)
    if job.object_kind in set(query.get("preferred_kinds", [])):
        score += 0.8
    score += 0.5 * source_quality_score(job)
    if grouped_term_hit(job, query):
        score += 3.0
    if term_hit(job, query.get("negative_terms", [])):
        score -= 4.0
    return score


def select_candidate_indexes(
    query: dict[str, Any],
    jobs: list[VectorJob],
    candidate_policy: str = "all",
    candidate_cap: int = 0,
) -> tuple[list[int], int]:
    before_count = len(jobs)
    if candidate_policy == "all":
        indexes = list(range(len(jobs)))
        return (indexes[:candidate_cap] if candidate_cap > 0 else indexes), before_count
    if candidate_policy != "prefilter_v1":
        raise ValueError(f"unknown candidate_policy={candidate_policy}")
    scored = (
        (candidate_prefilter_score(query, job), source_quality_score(job), idx)
        for idx, job in enumerate(jobs)
    )
    if candidate_cap > 0:
        top = heapq.nlargest(candidate_cap, scored, key=lambda item: (item[0], item[1], -item[2]))
    else:
        top = sorted(scored, key=lambda item: (item[0], item[1], -item[2]), reverse=True)
    return [idx for _, _, idx in top], before_count


def source_quality_score(job: VectorJob) -> float:
    metadata = job.metadata or {}
    lane = str(metadata.get("source_lane", "")).lower()
    account = str(metadata.get("source_account", metadata.get("account", ""))).lower()
    if not lane and "__" in account:
        lane = account.split("__", 1)[0]
    source_path = str(job.source_path).lower()
    if "stage7_bad_extracts" in source_path:
        return 0.45
    if "review" in lane or "review" in account:
        return 0.7
    if lane == "latest_free":
        return 1.0
    if "recovered" in lane:
        return 0.92
    if lane == "latest_dajiala_canary":
        return 0.85
    if lane == "free_signed_reexported":
        return 0.82
    return 0.78


def source_lane_label(job: VectorJob) -> str:
    metadata = job.metadata or {}
    lane = str(metadata.get("source_lane", "")).lower()
    if lane:
        return lane
    account = str(metadata.get("source_account", metadata.get("account", ""))).lower()
    if "__" in account:
        return account.split("__", 1)[0]
    return source_lane_from_values(account, str(job.source_path))


def account_label(job: VectorJob) -> str:
    metadata = job.metadata or {}
    for key in ("account_clean", "source_account_clean", "account", "source_account"):
        value = str(metadata.get(key, "")).strip()
        if value:
            if "__" in value:
                value = value.split("__", 1)[1]
            return value
    return ""


def is_review_source(job: VectorJob) -> bool:
    lane = source_lane_label(job)
    account = account_label(job).lower()
    return "review" in lane or "review" in account


def final_score(query: dict[str, Any], cosine_score: float, job: VectorJob, score_profile: str = "soft_payload") -> float:
    if score_profile == "cosine":
        return cosine_score
    payload = payload_match(query, job)
    confidence = job.metadata.get("confidence") if job.metadata else None
    evidence_bonus = 1.0 if (job.metadata or {}).get("evidence_ref") else 0.0
    confidence_score = float(confidence) if isinstance(confidence, (int, float)) else 0.7
    if score_profile == "soft_payload":
        return 0.60 * cosine_score + 0.15 * payload + 0.20 * confidence_score + 0.05 * evidence_bonus
    if score_profile == "intent_v2":
        payload_v2 = payload_match_v2(query, job)
        completeness = float((job.metadata or {}).get("field_completeness_weight") or 1.0)
        completeness = max(0.0, min(completeness, 1.2))
        return (
            0.50 * cosine_score
            + 0.30 * payload_v2
            + 0.08 * confidence_score
            + 0.05 * evidence_bonus
            + 0.07 * completeness
        )
    if score_profile == "source_adaptive":
        payload_v2 = payload_match_v2(query, job)
        completeness = float((job.metadata or {}).get("field_completeness_weight") or 1.0)
        completeness = max(0.0, min(completeness, 1.2))
        source_quality = source_quality_score(job)
        lexical = lexical_overlap_score(query, job)
        return (
            0.44 * cosine_score
            + 0.25 * payload_v2
            + 0.10 * source_quality
            + 0.07 * lexical
            + 0.06 * confidence_score
            + 0.04 * evidence_bonus
            + 0.04 * completeness
        )
    if score_profile == "adaptive_v3":
        payload_v2 = payload_match_v2(query, job)
        completeness = float((job.metadata or {}).get("field_completeness_weight") or 1.0)
        completeness = max(0.0, min(completeness, 1.2))
        source_quality = source_quality_score(job)
        lexical = lexical_overlap_score(query, job)
        kind_fit = intent_kind_score(query, job)
        intent = normalized_query_intent(query)
        if intent in {"venue_lookup", "person_lookup", "article_lookup", "account_lookup", "ocr_evidence_lookup"}:
            return (
                0.32 * cosine_score
                + 0.28 * payload_v2
                + 0.14 * lexical
                + 0.12 * kind_fit
                + 0.08 * source_quality
                + 0.03 * confidence_score
                + 0.02 * completeness
                + 0.01 * evidence_bonus
            )
        if intent in {"event_lookup", "broad_event"}:
            return (
                0.38 * cosine_score
                + 0.24 * payload_v2
                + 0.11 * kind_fit
                + 0.10 * source_quality
                + 0.07 * lexical
                + 0.04 * confidence_score
                + 0.04 * evidence_bonus
                + 0.02 * completeness
            )
        return (
            0.42 * cosine_score
            + 0.24 * payload_v2
            + 0.10 * source_quality
            + 0.10 * lexical
            + 0.06 * kind_fit
            + 0.04 * confidence_score
            + 0.02 * evidence_bonus
            + 0.02 * completeness
        )
    if score_profile == "adaptive_v3_source_guard":
        base = final_score(query, cosine_score, job, score_profile="adaptive_v3")
        source_quality = source_quality_score(job)
        if source_quality < 0.7:
            return base - 0.14
        if source_quality < 0.8:
            return base - 0.05
        if source_quality >= 1.0:
            return base + 0.015
        return base
    if score_profile == "adaptive_v4_source_gate":
        base = final_score(query, cosine_score, job, score_profile="adaptive_v3")
        source_quality = source_quality_score(job)
        min_top1 = query.get("min_top1_source_quality")
        penalty = 0.0
        has_source_gate = isinstance(min_top1, (int, float))
        if source_quality < 0.7:
            penalty -= 0.22 if has_source_gate else 0.16
        elif source_quality < 0.8:
            penalty -= 0.16 if has_source_gate else 0.08
        elif source_quality < 0.9:
            penalty -= 0.04 if has_source_gate else 0.015
        if has_source_gate and source_quality < float(min_top1):
            penalty -= 0.08
        if is_review_source(job):
            penalty -= 0.04 if has_source_gate else 0.015
        if source_quality >= 1.0:
            penalty += 0.025
        return base + penalty
    raise ValueError(f"unknown score_profile={score_profile}")


def evaluate_variant(
    jobs: list[VectorJob],
    queries: list[dict[str, Any]] | None = None,
    score_profile: str = "soft_payload",
    cache: EmbeddingCache | None = None,
    candidate_policy: str = "all",
    candidate_cap: int = 0,
) -> dict[str, Any]:
    if not jobs:
        return {"job_count": 0, "error": "no_jobs"}
    endpoint = jobs[0].endpoint
    model = jobs[0].model
    dim = jobs[0].dim
    vectors = [
        normalize(
            cache.get_or_embed(endpoint, model, job.canonical_text, dim)
            if cache
            else embed_text(endpoint, model, job.canonical_text, dim)
        )
        for job in jobs
    ]
    query_results = []
    mrr_sum = 0.0
    recall5 = 0
    city_precision_values = []
    kind_precision_values = []
    negative_leaks = 0
    rank1_hits = 0
    source_quality_values = []
    bad_source_leaks = 0
    eval_queries = queries or GOLDEN_QUERIES
    candidate_before_values = []
    candidate_scored_values = []
    review_lane_top3_queries = 0
    low_source_top3_queries = 0
    unique_account_values = []
    unique_city_values = []
    event_card_share_values = []
    hard_negative_query_count = 0
    hard_negative_passes = 0
    source_gate_query_count = 0
    source_gate_passes = 0
    by_intent: dict[str, dict[str, float]] = {}

    for query in eval_queries:
        intent = normalized_query_intent(query)
        qvec = normalize(
            cache.get_or_embed(endpoint, model, query["query"], dim)
            if cache
            else embed_text(endpoint, model, query["query"], dim)
        )
        candidate_indexes, candidate_before = select_candidate_indexes(
            query,
            jobs,
            candidate_policy=candidate_policy,
            candidate_cap=candidate_cap,
        )
        candidate_before_values.append(candidate_before)
        candidate_scored_values.append(len(candidate_indexes))
        ranked = []
        for idx in candidate_indexes:
            job = jobs[idx]
            vector = vectors[idx]
            cos = cosine(qvec, vector)
            ranked.append((final_score(query, cos, job, score_profile=score_profile), cos, idx, job))
        top10 = heapq.nlargest(10, ranked, key=lambda item: (item[0], item[1], -item[2]))
        top10_jobs = [job for _, _, _, job in top10]
        top3_jobs = top10_jobs[:3]
        first_hit_rank = None
        for idx, (_, _, _, job) in enumerate(top10, 1):
            if grouped_term_hit(job, query):
                first_hit_rank = idx
                break
        if first_hit_rank:
            mrr_sum += 1.0 / first_hit_rank
        if first_hit_rank == 1:
            rank1_hits += 1
        top5_hit = any(grouped_term_hit(job, query) for _, _, _, job in top10[:5])
        if top5_hit:
            recall5 += 1
        city_precision = None
        if query.get("city"):
            city_hits = sum(1 for _, _, _, job in top10 if (job.metadata or {}).get("city") == query["city"])
            city_precision = city_hits / max(len(top10), 1)
            city_precision_values.append(city_precision)
        preferred = set(query.get("preferred_kinds", []))
        kind_precision = None
        if preferred:
            kind_hits = sum(1 for _, _, _, job in top10 if job.object_kind in preferred)
            kind_precision = kind_hits / max(len(top10), 1)
            kind_precision_values.append(kind_precision)
        intent_stat = by_intent.setdefault(
            intent,
            {
                "count": 0.0,
                "recall5": 0.0,
                "rank1": 0.0,
                "mrr": 0.0,
                "city_precision_sum": 0.0,
                "city_precision_count": 0.0,
                "kind_precision_sum": 0.0,
                "kind_precision_count": 0.0,
            },
        )
        intent_stat["count"] += 1
        intent_stat["recall5"] += 1 if top5_hit else 0
        intent_stat["rank1"] += 1 if first_hit_rank == 1 else 0
        intent_stat["mrr"] += (1.0 / first_hit_rank) if first_hit_rank else 0
        if city_precision is not None:
            intent_stat["city_precision_sum"] += city_precision
            intent_stat["city_precision_count"] += 1
        if kind_precision is not None:
            intent_stat["kind_precision_sum"] += kind_precision
            intent_stat["kind_precision_count"] += 1
        negative_leaks += sum(1 for _, _, _, job in top10 if term_hit(job, query.get("negative_terms", [])))
        source_quality_values.append(sum(source_quality_score(job) for _, _, _, job in top10) / max(len(top10), 1))
        bad_source_leaks += sum(1 for _, _, _, job in top10 if source_quality_score(job) < 0.7)
        if any(is_review_source(job) for job in top3_jobs):
            review_lane_top3_queries += 1
        if any(source_quality_score(job) < 0.8 for job in top3_jobs):
            low_source_top3_queries += 1
        accounts = {account_label(job) for job in top10_jobs if account_label(job)}
        cities = {str((job.metadata or {}).get("city", "")) for job in top10_jobs if (job.metadata or {}).get("city")}
        unique_account_values.append(len(accounts))
        unique_city_values.append(len(cities))
        event_card_share_values.append(sum(1 for job in top10_jobs if job.object_kind == "event") / max(len(top10_jobs), 1))
        top1 = top10_jobs[0] if top10_jobs else None
        min_top1 = query.get("min_top1_source_quality")
        source_gate_pass = None
        if isinstance(min_top1, (int, float)):
            source_gate_query_count += 1
            source_gate_pass = bool(top1 and source_quality_score(top1) >= float(min_top1))
            if source_gate_pass:
                source_gate_passes += 1
        hard_negative_pass = None
        if query.get("hard_negative"):
            hard_negative_query_count += 1
            city_ok = True
            if query.get("city") and top1:
                city_ok = (top1.metadata or {}).get("city") == query["city"]
            negative_ok = not any(term_hit(job, query.get("negative_terms", [])) for job in top10_jobs)
            source_ok = source_gate_pass if source_gate_pass is not None else True
            hard_negative_pass = bool(first_hit_rank and first_hit_rank <= 5 and city_ok and negative_ok and source_ok)
            if hard_negative_pass:
                hard_negative_passes += 1
        query_results.append(
            {
                "id": query["id"],
                "query": query["query"],
                "query_source": query.get("query_source", ""),
                "intent": intent,
                "hard_negative_type": query.get("hard_negative_type", ""),
                "first_hit_rank": first_hit_rank,
                "top5_hit": first_hit_rank is not None and first_hit_rank <= 5,
                "source_gate_pass": source_gate_pass,
                "hard_negative_pass": hard_negative_pass,
                "top3": [
                    {
                        "final_score": round(score, 4),
                        "cosine": round(cos, 4),
                        "kind": job.object_kind,
                        "city": (job.metadata or {}).get("city", ""),
                        "source_lane": (job.metadata or {}).get("source_lane", ""),
                        "source_quality": round(source_quality_score(job), 3),
                        "account_clean": (job.metadata or {}).get("account_clean", (job.metadata or {}).get("account", "")),
                        "title": (job.metadata or {}).get("title", (job.metadata or {}).get("article_title", "")),
                        "object_id": job.object_id,
                    }
                    for score, cos, _, job in top10[:3]
                ],
            }
        )
    return {
        "job_count": len(jobs),
        "score_profile": score_profile,
        "by_kind": dict(Counter(job.object_kind for job in jobs)),
        "by_source_lane": dict(Counter(str((job.metadata or {}).get("source_lane", "")) for job in jobs)),
        "query_count": len(eval_queries),
        "candidate_policy": candidate_policy,
        "candidate_cap": candidate_cap,
        "avg_candidates_before_cap": round(sum(candidate_before_values) / max(len(candidate_before_values), 1), 2),
        "avg_candidates_scored": round(sum(candidate_scored_values) / max(len(candidate_scored_values), 1), 2),
        "recall_at_5": round(recall5 / len(eval_queries), 4),
        "rank1_rate": round(rank1_hits / len(eval_queries), 4),
        "mrr_at_10": round(mrr_sum / len(eval_queries), 4),
        "city_precision_at_10": round(sum(city_precision_values) / max(len(city_precision_values), 1), 4),
        "object_kind_precision_at_10": round(sum(kind_precision_values) / max(len(kind_precision_values), 1), 4),
        "negative_leaks_at_10": negative_leaks,
        "source_quality_at_10": round(sum(source_quality_values) / max(len(source_quality_values), 1), 4),
        "bad_source_leaks_at_10": bad_source_leaks,
        "review_lane_top3_rate": round(review_lane_top3_queries / max(len(eval_queries), 1), 4),
        "low_source_top3_rate": round(low_source_top3_queries / max(len(eval_queries), 1), 4),
        "avg_unique_accounts_at_10": round(sum(unique_account_values) / max(len(unique_account_values), 1), 4),
        "avg_unique_cities_at_10": round(sum(unique_city_values) / max(len(unique_city_values), 1), 4),
        "event_card_share_at_10": round(sum(event_card_share_values) / max(len(event_card_share_values), 1), 4),
        "hard_negative_query_count": hard_negative_query_count,
        "hard_negative_pass_rate": round(hard_negative_passes / max(hard_negative_query_count, 1), 4),
        "source_gate_query_count": source_gate_query_count,
        "source_gate_pass_rate": round(source_gate_passes / max(source_gate_query_count, 1), 4),
        "by_intent": {
            intent: {
                "query_count": int(stat["count"]),
                "recall_at_5": round(stat["recall5"] / max(stat["count"], 1), 4),
                "rank1_rate": round(stat["rank1"] / max(stat["count"], 1), 4),
                "mrr_at_10": round(stat["mrr"] / max(stat["count"], 1), 4),
                "city_precision_at_10": round(stat["city_precision_sum"] / max(stat["city_precision_count"], 1), 4),
                "object_kind_precision_at_10": round(stat["kind_precision_sum"] / max(stat["kind_precision_count"], 1), 4),
            }
            for intent, stat in sorted(by_intent.items())
        },
        "queries": query_results,
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = ["# Stage8 Vector Semantic Eval", ""]
    lines.append(f"- sample_articles: `{report['sample_articles']}`")
    lines.append(f"- extract_scope: `{report.get('extract_scope', 'primary')}`")
    lines.append(f"- files_selected: `{report.get('files_selected', 0)}`")
    lines.append(f"- max_jobs_per_variant: `{report['max_jobs_per_variant']}`")
    lines.append(f"- score_profiles: `{','.join(report.get('score_profiles', []))}`")
    lines.append(f"- query_mode: `{report.get('query_mode', 'fixed')}`")
    lines.append(f"- query_count: `{report.get('query_count', 0)}`")
    if report.get("query_source_counts"):
        lines.append(f"- query_source_counts: `{json.dumps(report.get('query_source_counts', {}), ensure_ascii=False, sort_keys=True)}`")
    lines.append(f"- candidate_policy: `{report.get('candidate_policy', 'all')}`")
    lines.append(f"- candidate_cap: `{report.get('candidate_cap', 0)}`")
    if report.get("project_articles"):
        lines.append(f"- project_articles: `{report.get('project_articles')}`")
    if report.get("cache_stats"):
        lines.append(f"- embedding_cache: `{report['cache_stats'].get('path', '')}`")
        lines.append(f"- cache_hits_misses: `{report['cache_stats'].get('hits', 0)}/{report['cache_stats'].get('misses', 0)}`")
    lines.append(f"- writes: `none; in-memory embedding/cosine only`")
    lines.append("")
    lines.append("| variant | profile | jobs | projected_jobs | queries | avg_scored | Recall@5 | Rank1 | MRR@10 | city_precision@10 | kind_precision@10 | source_quality@10 | bad_source_leaks@10 | review_top3 | low_source_top3 | source_gate_pass | hard_neg_pass | unique_accounts@10 | event_share@10 | negative_leaks@10 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name, result in report["variants"].items():
        lines.append(
            f"| {name} | {result.get('score_profile', '')} | {result.get('job_count', 0)} | "
            f"{result.get('projected_job_count', '')} | {result.get('query_count', 0)} | "
            f"{result.get('avg_candidates_scored', 0)} | {result.get('recall_at_5', 0)} | {result.get('rank1_rate', 0)} | "
            f"{result.get('mrr_at_10', 0)} | {result.get('city_precision_at_10', 0)} | "
            f"{result.get('object_kind_precision_at_10', 0)} | {result.get('source_quality_at_10', 0)} | "
            f"{result.get('bad_source_leaks_at_10', 0)} | {result.get('review_lane_top3_rate', 0)} | "
            f"{result.get('low_source_top3_rate', 0)} | {result.get('source_gate_pass_rate', 0)} | "
            f"{result.get('hard_negative_pass_rate', 0)} | {result.get('avg_unique_accounts_at_10', 0)} | "
            f"{result.get('event_card_share_at_10', 0)} | {result.get('negative_leaks_at_10', 0)} |"
        )
    lines.append("")
    lines.append("## By Intent")
    lines.append("")
    lines.append("| variant | intent | queries | Recall@5 | Rank1 | MRR@10 | city_precision@10 | kind_precision@10 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for name, result in report["variants"].items():
        for intent, item in result.get("by_intent", {}).items():
            lines.append(
                f"| {name} | {intent} | {item.get('query_count', 0)} | "
                f"{item.get('recall_at_5', 0)} | {item.get('rank1_rate', 0)} | "
                f"{item.get('mrr_at_10', 0)} | {item.get('city_precision_at_10', 0)} | "
                f"{item.get('object_kind_precision_at_10', 0)} |"
            )
    lines.append("")
    lines.append("## Top Results")
    for name, result in report["variants"].items():
        lines.append(f"\n### {name}")
        for query in result.get("queries", []):
            lines.append(f"- `{query['id']}` rank={query['first_hit_rank']} top5={query['top5_hit']}")
            for row in query.get("top3", []):
                lines.append(
                    f"  - {row['kind']} | {row['city']} | {row.get('source_lane', '')} | "
                    f"{row['account_clean']} | {row['title']} | final={row['final_score']} "
                    f"cos={row['cosine']} source_q={row.get('source_quality', '')}"
                )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage8 vector semantic eval")
    parser.add_argument("--output", default=r"D:\downstream_results\stage7_rewrite", help="Stage7 output root")
    parser.add_argument("--sample", type=int, default=40, help="Sample extract.article.v1.json files")
    parser.add_argument("--max-jobs", type=int, default=160, help="Max jobs per variant")
    parser.add_argument("--variants", default="baseline,labeled_v2,multi_card", help="Comma-separated variants")
    parser.add_argument("--score-profiles", default="soft_payload", help=f"Comma-separated score profiles: {','.join(SCORE_PROFILES)}")
    parser.add_argument("--extract-scope", default="primary", choices=["primary", "all"], help="primary=llm_extract only; all=all extract.article.v1.json under output root")
    parser.add_argument("--query-mode", default="fixed", choices=["fixed", "auto", "combined", "hard", "combined_hard"], help="fixed=manual golden queries; auto=generated weak-label queries; hard=hard-negative probes; combined=golden+auto; combined_hard=golden+auto+hard")
    parser.add_argument("--auto-query-limit", type=int, default=120, help="Maximum generated weak-label queries")
    parser.add_argument("--auto-query-per-article", type=int, default=4, help="Maximum generated weak-label queries per article")
    parser.add_argument("--hard-negative-limit", type=int, default=120, help="Maximum generated hard-negative queries")
    parser.add_argument("--hard-negative-per-article", type=int, default=4, help="Maximum generated hard-negative queries per article")
    parser.add_argument("--candidate-policy", default="all", choices=["all", "prefilter_v1"], help="Candidate selection before vector rerank")
    parser.add_argument("--candidate-cap", type=int, default=0, help="Max candidates reranked per query after candidate policy")
    parser.add_argument("--project-articles", type=int, default=0, help="Project job counts to this article volume without duplicating vectors")
    parser.add_argument("--endpoint-url", default=None, help="Override embedding endpoint URL, useful for Mac-local runs")
    parser.add_argument("--endpoint-model", default=None, help="Override embedding request model for candidate-model eval lanes")
    parser.add_argument("--endpoint-dim", type=int, default=None, help="Override expected embedding dimension for candidate-model eval lanes")
    parser.add_argument("--report-dir", default=None, help="Report directory")
    parser.add_argument("--cache-path", default=None, help="Embedding cache JSON path")
    parser.add_argument("--no-cache", action="store_true", help="Disable local embedding cache")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    output_root = Path(args.output)
    report_dir = Path(args.report_dir) if args.report_dir else output_root / "stage8" / "semantic_eval"
    report_dir.mkdir(parents=True, exist_ok=True)
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    score_profiles = [v.strip() for v in args.score_profiles.split(",") if v.strip()]
    unknown_profiles = sorted(set(score_profiles) - set(SCORE_PROFILES))
    if unknown_profiles:
        print(f"ERROR: unknown score profiles: {unknown_profiles}")
        return 1
    cache = None
    if not args.no_cache:
        cache_path = Path(args.cache_path) if args.cache_path else output_root / "stage8" / "semantic_eval_cache" / "embedding_cache.json"
        cache = EmbeddingCache(cache_path)
    extract_files = iter_extract_files(output_root, args.sample, extract_scope=args.extract_scope)
    eval_queries = build_eval_queries(
        output_root,
        extract_files,
        query_mode=args.query_mode,
        auto_query_limit=args.auto_query_limit,
        auto_query_per_article=args.auto_query_per_article,
        hard_negative_limit=args.hard_negative_limit,
        hard_negative_per_article=args.hard_negative_per_article,
    )
    query_source_counts = Counter(str(query.get("query_source", "unknown")) for query in eval_queries)
    endpoint, model, dim, route = load_vector_route(
        root,
        endpoint_override=args.endpoint_url,
        model_override=args.endpoint_model,
        dim_override=args.endpoint_dim,
    )
    report: dict[str, Any] = {
        "schema_version": "stage8_vector_semantic_eval.v3",
        "sample_articles": args.sample,
        "extract_scope": args.extract_scope,
        "files_selected": len(extract_files),
        "max_jobs_per_variant": args.max_jobs,
        "score_profiles": score_profiles,
        "query_mode": args.query_mode,
        "query_count": len(eval_queries),
        "query_source_counts": dict(query_source_counts),
        "fixed_query_count": query_source_counts.get("fixed", 0),
        "auto_query_count": query_source_counts.get("auto", 0),
        "hard_negative_query_count": query_source_counts.get("hard_negative", 0),
        "auto_query_per_article": args.auto_query_per_article,
        "hard_negative_per_article": args.hard_negative_per_article,
        "candidate_policy": args.candidate_policy,
        "candidate_cap": args.candidate_cap,
        "project_articles": args.project_articles,
        "embedding_route": {
            **route,
            "endpoint": endpoint,
            "model": model,
            "dim": dim,
            "override_active": bool(args.endpoint_url or args.endpoint_model or args.endpoint_dim),
        },
        "variants": {},
    }
    for variant in variants:
        jobs = build_variant_jobs_from_files(
            root,
            output_root,
            variant,
            extract_files,
            args.max_jobs,
            endpoint_override=args.endpoint_url,
            model_override=args.endpoint_model,
            dim_override=args.endpoint_dim,
        )
        for profile in score_profiles:
            result_key = variant if score_profiles == ["soft_payload"] else f"{variant}/{profile}"
            result = evaluate_variant(
                jobs,
                queries=eval_queries,
                score_profile=profile,
                cache=cache,
                candidate_policy=args.candidate_policy,
                candidate_cap=args.candidate_cap,
            )
            result["card_template"] = variant
            if args.project_articles and report["files_selected"]:
                result["projected_article_count"] = args.project_articles
                result["projected_job_count"] = round(result.get("job_count", 0) * args.project_articles / report["files_selected"])
            report["variants"][result_key] = result

    if cache:
        cache.save()
        report["cache_stats"] = cache.stats()

    json_path = report_dir / "stage8_vector_semantic_eval.json"
    md_path = report_dir / "stage8_vector_semantic_eval.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(md_path, report)
    print(json.dumps({"ok": True, "json": str(json_path), "markdown": str(md_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
